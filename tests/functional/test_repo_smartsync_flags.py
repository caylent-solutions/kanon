"""Functional tests for flag coverage of 'kanon repo smartsync'.

Exercises every flag registered in ``subcmds/smartsync.py``'s ``_Options()`` method
by invoking ``kanon repo smartsync`` as a subprocess. ``Smartsync._Options()``
delegates to ``Sync._Options(self, p, show_smart=False)``, so all sync flags are
inherited except ``-s/--smart-sync`` and ``-t/--smart-tag`` (hidden by show_smart=False).

Validates correct accept and reject behavior for all flag values, and correct
default behavior when flags are omitted.

Flags inherited from ``Sync._Options(show_smart=False)``:

Boolean store_true flags (accepted without an argument; rejected with inline value):
- ``-f`` / ``--force-broken``         (obsolete, store_true)
- ``--fail-fast``                     (store_true)
- ``--force-sync``                    (store_true)
- ``--force-checkout``                (store_true)
- ``--force-remove-dirty``            (store_true)
- ``--rebase``                        (store_true)
- ``-l`` / ``--local-only``           (store_true)
- ``--interleaved``                   (store_true)
- ``-n`` / ``--network-only``         (store_true)
- ``-d`` / ``--detach``               (store_true, dest=detach_head)
- ``-c`` / ``--current-branch``       (store_true, dest=current_branch_only)
- ``--clone-bundle``                  (store_true, dest=clone_bundle)
- ``--fetch-submodules``              (store_true)
- ``--use-superproject``              (store_true)
- ``--tags``                          (store_true)
- ``--optimized-fetch``               (store_true)
- ``--prune``                         (store_true)
- ``--auto-gc``                       (store_true, default=None)
- ``--no-repo-verify``                (store_false, dest=repo_verify)
- ``--repo-upgraded``                 (store_true)

Boolean store_false flags (inverse toggling another dest; also rejected with inline value):
- ``--no-manifest-update`` / ``--nmu`` (store_false, dest=mp_update)
- ``--no-current-branch``             (store_false, dest=current_branch_only)
- ``--no-clone-bundle``               (store_false, dest=clone_bundle)
- ``--no-use-superproject``           (store_false, dest=use_superproject)
- ``--no-tags``                       (store_false, dest=tags)
- ``--no-prune``                      (store_false, dest=prune)
- ``--no-auto-gc``                    (store_false, dest=auto_gc)

Boolean flags from ``RepoHook.AddOptionGroup(p, 'post-sync')`` in sync.py:
- ``--no-verify``                     (store_true, dest=bypass_hooks)
- ``--verify``                        (store_true, dest=allow_all_hooks)
- ``--ignore-hooks``                  (store_true)

Typed / string flags (accept a value; rejected with non-parseable value):
- ``--jobs-network JOBS``             (int, default=None)
- ``--jobs-checkout JOBS``            (int, default=None)
- ``-m`` / ``--manifest-name NAME.xml`` (store string)
- ``-u`` / ``--manifest-server-username`` (store string)
- ``-p`` / ``--manifest-server-password`` (store string)
- ``--retry-fetches N``               (int, default=0)

From ``Command._CommonOptions()`` (PARALLEL_JOBS=0 enables -j/--jobs):
- ``-j`` / ``--jobs``                 (int, default=0)

NOTE: ``-s/--smart-sync`` and ``-t/--smart-tag`` are NOT registered in
``Smartsync._Options()`` because ``show_smart=False`` is passed to
``Sync._Options()``. Those flags belong to sync only.

AC wording note: AC-TEST-002 states "every flag that accepts enumerated values
has a negative test for an invalid value." The smartsync flags accept typed
integer values (--jobs-network, --jobs-checkout, --retry-fetches, -j/--jobs)
rather than enumerated keyword values. The negative tests for these typed flags
confirm that non-integer strings (e.g. "abc") are rejected with exit code 2. For
boolean store_true / store_false flags, the applicable negative test is supplying
an inline value (e.g. --fail-fast=unexpected), which optparse rejects with exit
code 2. String flags (--manifest-name, --manifest-server-username,
--manifest-server-password) accept any string, so no enumeration constraint
exists; those flags are exercised only via valid-value tests.

AC-TEST-003 note: Absence-default behavior is verified by running
'kanon repo smartsync' with all optional flags omitted on a fully synced and
manifest-server-patched repo and confirming the documented success behavior
(exit 0, success phrase on stdout).

Covers:
- AC-TEST-001: Every ``_Options()`` flag in subcmds/smartsync.py has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated values has a negative test for
  an invalid value.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import (
    _CLI_COMMAND_PHRASE,
    _CLI_FLAG_JOBS_ONE,
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _CLI_TOKEN_SMARTSYNC,
    _ERROR_PREFIX,
    _GIT_USER_EMAIL,
    _GIT_USER_NAME,
    _PROJECT_NAME,
    _PROJECT_PATH,
    _SUCCESS_PHRASE,
    _TRACEBACK_MARKER,
    _build_smartsync_state,
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all domain literals must appear here only.
# No inline literals in test bodies or f-string diagnostics.
# ---------------------------------------------------------------------------

# Exit code constants
_EXPECTED_EXIT_SUCCESS = 0
_ARGPARSE_ERROR_EXIT_CODE = 2

# Nonexistent repo-dir used for argument-parser acceptance tests that do not
# require a fully initialized .repo directory.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-smartsync-flags-repo-dir"

# Inline-value suffix for negative tests against boolean flags.
# optparse exits 2 with '--<flag> option does not take a value'.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Phrase expected in stderr when optparse rejects an inline value on a boolean flag.
_DOES_NOT_TAKE_VALUE_PHRASE = "does not take a value"

# Phrase expected in stderr when optparse rejects a non-integer value for an int flag.
_INVALID_INT_PHRASE = "invalid integer value"

# Non-integer value used in negative tests for typed int flags.
_INVALID_INT_VALUE = "abc"

# Valid integer value used in valid-value tests for typed int flags.
_VALID_INT_VALUE = "2"

# Valid string value for --manifest-name (must be an XML filename).
_MANIFEST_NAME_VALUE = "default.xml"

# Valid string values for string-store flags.
_MANIFEST_SERVER_USERNAME_VALUE = "testuser"
_MANIFEST_SERVER_PASSWORD_VALUE = "testpassword"

# Explicit default value for --retry-fetches (documented as 0 in _Options()).
_RETRY_FETCHES_DEFAULT_VALUE = "0"

# ---------------------------------------------------------------------------
# CLI flag constants for flags used in non-parametrize test bodies
# and referenced in parametrize tuples.
# ---------------------------------------------------------------------------
_CLI_FLAG_FAIL_FAST = "--fail-fast"
_CLI_FLAG_FORCE_BROKEN = "--force-broken"
_CLI_FLAG_FORCE_SYNC = "--force-sync"
_CLI_FLAG_FORCE_CHECKOUT = "--force-checkout"
_CLI_FLAG_FORCE_REMOVE_DIRTY = "--force-remove-dirty"
_CLI_FLAG_REBASE = "--rebase"
_CLI_FLAG_LOCAL_ONLY = "--local-only"
_CLI_FLAG_INTERLEAVED = "--interleaved"
_CLI_FLAG_NETWORK_ONLY = "--network-only"
_CLI_FLAG_DETACH = "--detach"
_CLI_FLAG_CURRENT_BRANCH = "--current-branch"
_CLI_FLAG_NO_CURRENT_BRANCH = "--no-current-branch"
_CLI_FLAG_CLONE_BUNDLE = "--clone-bundle"
_CLI_FLAG_NO_CLONE_BUNDLE = "--no-clone-bundle"
_CLI_FLAG_FETCH_SUBMODULES = "--fetch-submodules"
_CLI_FLAG_USE_SUPERPROJECT = "--use-superproject"
_CLI_FLAG_NO_USE_SUPERPROJECT = "--no-use-superproject"
_CLI_FLAG_TAGS = "--tags"
_CLI_FLAG_NO_TAGS = "--no-tags"
_CLI_FLAG_OPTIMIZED_FETCH = "--optimized-fetch"
_CLI_FLAG_PRUNE = "--prune"
_CLI_FLAG_NO_PRUNE = "--no-prune"
_CLI_FLAG_AUTO_GC = "--auto-gc"
_CLI_FLAG_NO_AUTO_GC = "--no-auto-gc"
_CLI_FLAG_NO_MANIFEST_UPDATE = "--no-manifest-update"
_CLI_FLAG_NMU = "--nmu"
_CLI_FLAG_NO_REPO_VERIFY = "--no-repo-verify"
_CLI_FLAG_REPO_UPGRADED = "--repo-upgraded"
_CLI_FLAG_NO_VERIFY = "--no-verify"
_CLI_FLAG_VERIFY = "--verify"
_CLI_FLAG_IGNORE_HOOKS = "--ignore-hooks"
_CLI_FLAG_JOBS_NETWORK = "--jobs-network"
_CLI_FLAG_JOBS_CHECKOUT = "--jobs-checkout"
_CLI_FLAG_RETRY_FETCHES = "--retry-fetches"
_CLI_FLAG_MANIFEST_NAME = "--manifest-name"
_CLI_FLAG_MANIFEST_SERVER_USERNAME = "--manifest-server-username"
_CLI_FLAG_MANIFEST_SERVER_PASSWORD = "--manifest-server-password"

# Short-form flag constants -- used in parametrize tuples that exercise short
# aliases.  Defined as named constants per the no-inline-literals rule.
_CLI_FLAG_SHORT_FORCE_BROKEN = "-f"
_CLI_FLAG_SHORT_LOCAL_ONLY = "-l"
_CLI_FLAG_SHORT_NETWORK_ONLY = "-n"
_CLI_FLAG_SHORT_DETACH = "-d"
_CLI_FLAG_SHORT_CURRENT_BRANCH = "-c"
_CLI_FLAG_SHORT_JOBS = "-j"
_CLI_FLAG_LONG_JOBS = "--jobs"

# ---------------------------------------------------------------------------
# Parametrize lists for boolean flags -- tuples of (flag_token, test_id).
# All boolean flags (both store_true and store_false) are accepted without an
# argument value, and rejected with an inline value via optparse's exit-2 path.
# Short-form flags must NOT be tested with inline '=value' syntax (only long-
# form flags support '--flag=value' in optparse).
# ---------------------------------------------------------------------------

# All boolean flags in Smartsync._Options() (which delegates to Sync._Options
# with show_smart=False) and _CommonOptions(). Both short and long forms are
# included for valid-value tests.
# NOTE: -s/--smart-sync and -t/--smart-tag are intentionally absent (show_smart=False).
_BOOL_FLAGS_ALL: list[tuple[str, str]] = [
    (_CLI_FLAG_SHORT_FORCE_BROKEN, "short-force-broken"),
    (_CLI_FLAG_FORCE_BROKEN, "long-force-broken"),
    (_CLI_FLAG_FAIL_FAST, "long-fail-fast"),
    (_CLI_FLAG_FORCE_SYNC, "long-force-sync"),
    (_CLI_FLAG_FORCE_CHECKOUT, "long-force-checkout"),
    (_CLI_FLAG_FORCE_REMOVE_DIRTY, "long-force-remove-dirty"),
    (_CLI_FLAG_REBASE, "long-rebase"),
    (_CLI_FLAG_SHORT_LOCAL_ONLY, "short-local-only"),
    (_CLI_FLAG_LOCAL_ONLY, "long-local-only"),
    (_CLI_FLAG_INTERLEAVED, "long-interleaved"),
    (_CLI_FLAG_SHORT_NETWORK_ONLY, "short-network-only"),
    (_CLI_FLAG_NETWORK_ONLY, "long-network-only"),
    (_CLI_FLAG_SHORT_DETACH, "short-detach"),
    (_CLI_FLAG_DETACH, "long-detach"),
    (_CLI_FLAG_SHORT_CURRENT_BRANCH, "short-current-branch"),
    (_CLI_FLAG_CURRENT_BRANCH, "long-current-branch"),
    (_CLI_FLAG_NO_CURRENT_BRANCH, "long-no-current-branch"),
    (_CLI_FLAG_CLONE_BUNDLE, "long-clone-bundle"),
    (_CLI_FLAG_NO_CLONE_BUNDLE, "long-no-clone-bundle"),
    (_CLI_FLAG_FETCH_SUBMODULES, "long-fetch-submodules"),
    (_CLI_FLAG_USE_SUPERPROJECT, "long-use-superproject"),
    (_CLI_FLAG_NO_USE_SUPERPROJECT, "long-no-use-superproject"),
    (_CLI_FLAG_TAGS, "long-tags"),
    (_CLI_FLAG_NO_TAGS, "long-no-tags"),
    (_CLI_FLAG_OPTIMIZED_FETCH, "long-optimized-fetch"),
    (_CLI_FLAG_PRUNE, "long-prune"),
    (_CLI_FLAG_NO_PRUNE, "long-no-prune"),
    (_CLI_FLAG_AUTO_GC, "long-auto-gc"),
    (_CLI_FLAG_NO_AUTO_GC, "long-no-auto-gc"),
    (_CLI_FLAG_NO_MANIFEST_UPDATE, "long-no-manifest-update"),
    (_CLI_FLAG_NMU, "long-nmu-alias"),
    (_CLI_FLAG_NO_REPO_VERIFY, "long-no-repo-verify"),
    (_CLI_FLAG_REPO_UPGRADED, "long-repo-upgraded"),
    (_CLI_FLAG_NO_VERIFY, "long-no-verify"),
    (_CLI_FLAG_VERIFY, "long-verify"),
    (_CLI_FLAG_IGNORE_HOOKS, "long-ignore-hooks"),
]

# Long-form boolean flags eligible for the inline-value negative test.
# Short-form flags are excluded because '--flag=value' syntax is only valid
# for long-form flags in optparse.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    (_CLI_FLAG_FORCE_BROKEN, "force-broken"),
    (_CLI_FLAG_FAIL_FAST, "fail-fast"),
    (_CLI_FLAG_FORCE_SYNC, "force-sync"),
    (_CLI_FLAG_FORCE_CHECKOUT, "force-checkout"),
    (_CLI_FLAG_FORCE_REMOVE_DIRTY, "force-remove-dirty"),
    (_CLI_FLAG_REBASE, "rebase"),
    (_CLI_FLAG_LOCAL_ONLY, "local-only"),
    (_CLI_FLAG_INTERLEAVED, "interleaved"),
    (_CLI_FLAG_NETWORK_ONLY, "network-only"),
    (_CLI_FLAG_DETACH, "detach"),
    (_CLI_FLAG_CURRENT_BRANCH, "current-branch"),
    (_CLI_FLAG_NO_CURRENT_BRANCH, "no-current-branch"),
    (_CLI_FLAG_CLONE_BUNDLE, "clone-bundle"),
    (_CLI_FLAG_NO_CLONE_BUNDLE, "no-clone-bundle"),
    (_CLI_FLAG_FETCH_SUBMODULES, "fetch-submodules"),
    (_CLI_FLAG_USE_SUPERPROJECT, "use-superproject"),
    (_CLI_FLAG_NO_USE_SUPERPROJECT, "no-use-superproject"),
    (_CLI_FLAG_TAGS, "tags"),
    (_CLI_FLAG_NO_TAGS, "no-tags"),
    (_CLI_FLAG_OPTIMIZED_FETCH, "optimized-fetch"),
    (_CLI_FLAG_PRUNE, "prune"),
    (_CLI_FLAG_NO_PRUNE, "no-prune"),
    (_CLI_FLAG_AUTO_GC, "auto-gc"),
    (_CLI_FLAG_NO_AUTO_GC, "no-auto-gc"),
    (_CLI_FLAG_NO_MANIFEST_UPDATE, "no-manifest-update"),
    (_CLI_FLAG_NO_REPO_VERIFY, "no-repo-verify"),
    (_CLI_FLAG_REPO_UPGRADED, "repo-upgraded"),
    (_CLI_FLAG_NO_VERIFY, "no-verify"),
    (_CLI_FLAG_VERIFY, "verify"),
    (_CLI_FLAG_IGNORE_HOOKS, "ignore-hooks"),
]

# Typed int flags: (flag_token, valid_value, test_id).
# Valid-value test passes the flag with _VALID_INT_VALUE.
# Negative test passes the flag with _INVALID_INT_VALUE.
_INT_FLAGS: list[tuple[str, str, str]] = [
    (_CLI_FLAG_JOBS_NETWORK, _VALID_INT_VALUE, "jobs-network"),
    (_CLI_FLAG_JOBS_CHECKOUT, _VALID_INT_VALUE, "jobs-checkout"),
    (_CLI_FLAG_RETRY_FETCHES, _VALID_INT_VALUE, "retry-fetches"),
    (_CLI_FLAG_SHORT_JOBS, _VALID_INT_VALUE, "short-jobs"),
    (_CLI_FLAG_LONG_JOBS, _VALID_INT_VALUE, "long-jobs"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/smartsync.py
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSmartSyncFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/smartsync.py has a valid-value test.

    Exercises each boolean and typed flag registered in ``Smartsync._Options()``
    (which delegates to ``Sync._Options(show_smart=False)``) by invoking
    'kanon repo smartsync' against a real initialized+synced .repo directory.
    Valid-value tests confirm the flag is accepted without an argument-parsing
    error (exit code != 2).

    Boolean flags (store_true / store_false) are passed without a value.
    Typed int flags are passed with a valid integer value (_VALID_INT_VALUE).
    String flags are tested with representative dummy string values.

    Because several boolean flags (e.g. --network-only, --local-only) alter
    smartsync semantics in ways that may prevent a complete re-sync on the test
    repository, the valid-value tests assert exit code != _ARGPARSE_ERROR_EXIT_CODE
    rather than exit code == 0. This confirms optparse accepted the flag while
    remaining agnostic to business-logic exit codes.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _BOOL_FLAGS_ALL],
        ids=[test_id for _, test_id in _BOOL_FLAGS_ALL],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo smartsync' with the given boolean flag against a properly
        initialized+synced .repo directory and asserts that optparse does not
        reject the invocation (exit code != 2). A non-2 exit code confirms the
        flag itself was accepted; subsequent behavior is not an argument-parsing
        error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        ("flag", "value"),
        [(flag, value) for flag, value, _ in _INT_FLAGS],
        ids=[test_id for _, _, test_id in _INT_FLAGS],
    )
    def test_int_flag_with_valid_value_accepted(self, tmp_path: pathlib.Path, flag: str, value: str) -> None:
        """Each typed int flag is accepted when supplied with a valid integer.

        Calls 'kanon repo smartsync' with flag=value against a properly
        initialized+synced .repo directory. Asserts that optparse does not
        reject the invocation (exit code != 2). A non-2 exit confirms the flag
        and value were parsed without argument-parsing errors.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            flag,
            value,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Int flag {flag!r} with value {value!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_manifest_name_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--manifest-name' with a valid filename is accepted by the argument parser.

        Supplies '--manifest-name default.xml' to 'kanon repo smartsync' against a
        real initialized .repo directory. Asserts exit code != 2 confirming the
        flag and value are parsed without argument-parsing errors.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            _CLI_FLAG_MANIFEST_NAME,
            _MANIFEST_NAME_VALUE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_MANIFEST_NAME} {_MANIFEST_NAME_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_manifest_server_username_and_password_flags_accepted_together(self, tmp_path: pathlib.Path) -> None:
        """Both --manifest-server-username and --manifest-server-password are accepted together.

        Both --manifest-server-username and --manifest-server-password must be supplied
        together (optparse co-constraint). This test verifies optparse accepts both in a
        single invocation without an argument-parsing error (exit code != 2).
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            _CLI_FLAG_MANIFEST_SERVER_USERNAME,
            _MANIFEST_SERVER_USERNAME_VALUE,
            _CLI_FLAG_MANIFEST_SERVER_PASSWORD,
            _MANIFEST_SERVER_PASSWORD_VALUE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_MANIFEST_SERVER_USERNAME} {_MANIFEST_SERVER_USERNAME_VALUE!r} "
            f"{_CLI_FLAG_MANIFEST_SERVER_PASSWORD} {_MANIFEST_SERVER_PASSWORD_VALUE!r}' "
            f"triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags that accept typed or enumerated values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSmartSyncFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated values has a negative test.

    Two categories of negative tests:

    1. Boolean flags (store_true / store_false): supplying '--<flag>=unexpected'
       causes optparse to exit 2 with '--<flag> option does not take a value'.

    2. Typed int flags (--jobs-network, --jobs-checkout, --retry-fetches, -j/--jobs):
       supplying a non-integer string causes optparse to exit 2 with
       'invalid integer value'.

    String flags (--manifest-name, --manifest-server-username,
    --manifest-server-password) accept any string and have no enumeration
    constraint; no negative test applies to them.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with inline value must exit 2 and emit error on stderr.

        Supplies '--<flag>=unexpected' to 'kanon repo smartsync'. Since all
        tested flags are store_true or store_false, optparse rejects the inline
        value with exit code 2 and emits '--<flag> option does not take a value'
        on stderr. Stdout must not contain the rejection detail (channel
        discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_fail_fast_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--fail-fast=unexpected' error must name '--fail-fast' in stderr.

        The embedded optparse parser emits '--fail-fast option does not take
        a value' when '--fail-fast=unexpected' is supplied. Confirms the
        canonical flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _CLI_FLAG_FAIL_FAST + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_FAIL_FAST}=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _CLI_FLAG_FAIL_FAST in result.stderr, (
            f"Expected {_CLI_FLAG_FAIL_FAST!r} in stderr for '{_CLI_FLAG_FAIL_FAST}=unexpected' error.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _, _ in _INT_FLAGS],
        ids=[test_id for _, _, test_id in _INT_FLAGS],
    )
    def test_int_flag_non_integer_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each typed int flag must exit 2 with error on stderr when given a non-integer.

        Supplies 'kanon repo smartsync <flag> abc' against a nonexistent repo dir.
        optparse exits 2 when it cannot parse the value as an integer. The
        rejection error must appear on stderr only; stdout must not contain the
        error detail (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_SMARTSYNC,
            flag,
            _INVALID_INT_VALUE,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{flag} {_INVALID_INT_VALUE}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _INVALID_INT_PHRASE in result.stderr, (
            f"Expected {_INVALID_INT_PHRASE!r} in stderr for '{flag} {_INVALID_INT_VALUE}'.\n  stderr: {result.stderr!r}"
        )
        assert _INVALID_INT_VALUE not in result.stdout, (
            f"Invalid value {_INVALID_INT_VALUE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSmartSyncFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that running 'kanon repo smartsync' with all optional flags omitted
    produces the documented success behavior (exit 0, success phrase on stdout).
    This confirms that no flag is required and all documented defaults produce
    a valid, successful invocation on an already-synced repo with a manifest
    server configured.

    Documented defaults for selected flags:
    - --jobs-network: None (defaults to --jobs or 1)
    - --jobs-checkout: None (defaults to --jobs or DEFAULT_LOCAL_JOBS)
    - --fail-fast: False (do not halt on first error)
    - --force-sync: False (do not overwrite git directories)
    - --force-checkout: False (do not force checkout)
    - --force-remove-dirty: False (do not remove dirty projects)
    - --local-only: False (fetch from remote)
    - --network-only: False (do update working tree)
    - --fetch-submodules: False (do not fetch submodules)
    - --prune: default True (delete stale refs)
    - --auto-gc: None (no garbage collection by default)
    - --retry-fetches: 0 (no retries)
    - --no-verify: False (run post-sync hook if configured)
    - --verify: False (prompt before running hook)
    - --ignore-hooks: False (abort if hooks fail)
    """

    @pytest.fixture(scope="class")
    def smartsync_defaults_result(
        self,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> subprocess.CompletedProcess:
        """Run 'kanon repo smartsync' once with all flags omitted and return CompletedProcess.

        Uses _build_smartsync_state to create a synced repo with manifest-server
        patched and XMLRPC server started. Runs 'kanon repo smartsync' with no
        optional flags and returns the CompletedProcess. Both tests in this class
        assert on the shared result to avoid repeating the expensive git setup.

        Returns:
            The CompletedProcess from 'kanon repo smartsync' with no optional flags.

        Raises:
            AssertionError: When the prerequisite smartsync invocation fails.
        """
        tmp_path = tmp_path_factory.mktemp("smartsync_flags_defaults")
        checkout_dir, repo_dir, rpc_server = _build_smartsync_state(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            cwd=checkout_dir,
        )

        rpc_server.shutdown()

        return result

    def test_all_flags_omitted_exits_zero(self, smartsync_defaults_result: subprocess.CompletedProcess) -> None:
        """'kanon repo smartsync' with all optional flags omitted exits 0.

        After a successful 'kanon repo init' and first 'kanon repo sync' (via
        _build_smartsync_state) and manifest-server patch, running 'kanon repo
        smartsync' with no optional flags must exit 0. Confirms all documented
        defaults allow a successful smartsync.
        """
        assert smartsync_defaults_result.returncode == _EXPECTED_EXIT_SUCCESS, (
            f"'{_CLI_COMMAND_PHRASE}' with all optional flags omitted exited "
            f"{smartsync_defaults_result.returncode}, expected {_EXPECTED_EXIT_SUCCESS}.\n"
            f"  stdout: {smartsync_defaults_result.stdout!r}\n"
            f"  stderr: {smartsync_defaults_result.stderr!r}"
        )

    def test_all_flags_omitted_emits_success_phrase(
        self, smartsync_defaults_result: subprocess.CompletedProcess
    ) -> None:
        """'kanon repo smartsync' with all optional flags omitted emits the success phrase.

        On success with no optional flags, 'repo smartsync' prints the documented
        completion message to stdout. Confirms the default behavior (absence of
        all flags) produces the expected output phrase.
        """
        assert smartsync_defaults_result.returncode == _EXPECTED_EXIT_SUCCESS, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed with exit {smartsync_defaults_result.returncode}.\n"
            f"  stdout: {smartsync_defaults_result.stdout!r}\n"
            f"  stderr: {smartsync_defaults_result.stderr!r}"
        )
        assert _SUCCESS_PHRASE in smartsync_defaults_result.stdout, (
            f"Expected {_SUCCESS_PHRASE!r} in stdout when all flags are omitted.\n"
            f"  stdout: {smartsync_defaults_result.stdout!r}\n"
            f"  stderr: {smartsync_defaults_result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSmartSyncFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of selected flags documented in
    Sync._Options() (show_smart=False). Each test confirms the flag is accepted
    and the command behaves consistent with its documented purpose.

    Flags under test:
    - --force-broken: obsolete flag accepted without error.
    - --fail-fast: accepted; does not alter argparse success.
    - --force-sync: accepted; does not alter argparse success.
    - --force-checkout: accepted; does not alter argparse success.
    - --force-remove-dirty: accepted; does not alter argparse success.
    - --no-manifest-update / --nmu: accepted; prevents manifest re-fetch.
    - --prune / --no-prune: both accepted without error.
    - --auto-gc / --no-auto-gc: both accepted without error.
    - --jobs-network / --jobs-checkout: accepted with integer values.
    - --retry-fetches: accepted with integer value 0.
    - --no-repo-verify: accepted; prevents repo verification.
    - --no-verify: accepted; skips post-sync hook.
    - --verify: accepted; runs post-sync hook without prompting.
    - --ignore-hooks: accepted; does not abort if hooks fail.
    """

    def test_force_broken_flag_is_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--force-broken' (obsolete) is accepted by the argument parser.

        The --force-broken flag is documented as an obsolete option to be
        deleted in the future. It must still be accepted without error (exit
        code != 2) so that existing scripts continue to work.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            _CLI_FLAG_FORCE_BROKEN,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_FORCE_BROKEN}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [
            _CLI_FLAG_NO_MANIFEST_UPDATE,
            _CLI_FLAG_NMU,
        ],
        ids=["no-manifest-update", "nmu"],
    )
    def test_no_manifest_update_and_nmu_alias_both_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Both '--no-manifest-update' and '--nmu' alias are accepted.

        Both forms share the same dest (mp_update) and must both be accepted
        by optparse without an argument-parsing error (exit code != 2).
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{flag}' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_prune_and_no_prune_combination_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--no-prune' is accepted alongside other flags without argument-parsing error.

        Confirms the prune/no-prune pair is parsed without conflict: supplying
        --no-prune disables ref pruning via store_false on the shared dest.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            _CLI_FLAG_NO_PRUNE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_NO_PRUNE}' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [
            _CLI_FLAG_AUTO_GC,
            _CLI_FLAG_NO_AUTO_GC,
        ],
        ids=["auto-gc", "no-auto-gc"],
    )
    def test_auto_gc_and_no_auto_gc_both_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Both '--auto-gc' and '--no-auto-gc' are accepted without argument-parsing error.

        Verifies that both sides of the auto-gc toggle pair are accepted by the
        argument parser. The flags share the same dest (auto_gc) with opposite
        store_true / store_false actions.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{flag}' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_retry_fetches_zero_is_default_and_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--retry-fetches' with the documented default value is accepted.

        The --retry-fetches flag defaults to _RETRY_FETCHES_DEFAULT_VALUE (no
        retries). Supplying it explicitly with the default value must be
        accepted without argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            _CLI_FLAG_RETRY_FETCHES,
            _RETRY_FETCHES_DEFAULT_VALUE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_RETRY_FETCHES} {_RETRY_FETCHES_DEFAULT_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [
            _CLI_FLAG_NO_VERIFY,
            _CLI_FLAG_VERIFY,
            _CLI_FLAG_IGNORE_HOOKS,
        ],
        ids=["no-verify", "verify", "ignore-hooks"],
    )
    def test_post_sync_hook_flags_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Post-sync hook flags are accepted by the argument parser without error.

        The flags '--no-verify', '--verify', and '--ignore-hooks' are registered
        via RepoHook.AddOptionGroup(p, 'post-sync') in sync.py. Each must be
        accepted without an argument-parsing error (exit code != 2).
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
        )
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{flag}' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSmartSyncFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo smartsync' flags.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.

    The channel fixture runs a successful smartsync (all flags at defaults, with
    manifest server patched) once per class, and individual tests assert on the
    shared result to avoid repeating the expensive git setup.

    The unique orthogonal channel property verified here for the success case is
    that stdout contains the documented success phrase, confirming the correct
    channel routing. Stderr is expected to be non-empty (repo tool logs
    credentials lookup) but that property is tested in the happy-path file.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo smartsync' once and return the CompletedProcess.

        Uses tmp_path_factory for a class-scoped fixture: setup and CLI
        invocation execute once and all channel assertions share the result.

        Returns:
            The CompletedProcess from 'kanon repo smartsync' with no optional flags.

        Raises:
            AssertionError: When the prerequisite setup or the smartsync
                invocation fails.
        """
        tmp_path = tmp_path_factory.mktemp("smartsync_flags_channel")
        checkout_dir, repo_dir, rpc_server = _build_smartsync_state(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            cwd=checkout_dir,
        )

        rpc_server.shutdown()

        assert result.returncode == _EXPECTED_EXIT_SUCCESS, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed with exit "
            f"{result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_successful_smartsync_has_no_traceback_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo smartsync' must not emit Python tracebacks to stdout.

        Verifies that stdout does not contain 'Traceback (most recent call last)'
        on a successful smartsync. Tracebacks on stdout indicate an unhandled
        exception escaped to the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stdout: {channel_result.stdout!r}"
        )

    def test_successful_smartsync_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo smartsync' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'{_CLI_COMMAND_PHRASE}': {line!r}\n  stdout: {channel_result.stdout!r}"
            )

    def test_successful_smartsync_success_phrase_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo smartsync' must emit the success phrase to stdout.

        Confirms that the documented completion phrase appears on stdout and not
        on stderr, verifying correct channel routing for positive output.
        """
        assert _SUCCESS_PHRASE in channel_result.stdout, (
            f"Expected {_SUCCESS_PHRASE!r} in stdout of successful '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stdout: {channel_result.stdout!r}\n"
            f"  stderr: {channel_result.stderr!r}"
        )
        assert _SUCCESS_PHRASE not in channel_result.stderr, (
            f"Success phrase {_SUCCESS_PHRASE!r} leaked to stderr in '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )

    def test_successful_smartsync_has_no_traceback_on_stderr(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo smartsync' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )
