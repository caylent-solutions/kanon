# Copyright (C) 2026 Caylent, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Regression guard for E0-F6-S1-T2: linkfile errors silently swallowed.

Bug reference: E0-F6-S1-T2 -- project.py _LinkFile.__linkIt contained a bare
except OSError clause that caught the exception and logged it without re-raising.
Any filesystem failure during symlink creation (permission denied, missing
parent directory, no space left on device) was silently swallowed, leaving the
caller with no indication that the link was not created.

Root cause: project.py _LinkFile.__linkIt lines 462-463 -- bare except OSError
catches the exception and calls logger.error() or similar, then returns normally.
The symlink is never created, but no exception propagates to the caller.

Fix (landed in E0-F6-S1-T2): Removed the silent swallow. The except clause
now re-raises with source and destination path context:
    except OSError as e:
        raise OSError(f"Cannot link file {relSrc!r} to {absDest!r}: {e}") from e

This regression guard asserts that:
1. OSError from symlink creation propagates out of _LinkFile._Link().
2. The exact bug condition (symlink fails; caller sees no exception) is blocked.
3. The exception message includes both source and destination path.
4. PermissionError (a subclass of OSError) propagates with exception chaining.
5. The raise-with-chaining guard is structurally present in the source code.
"""

import inspect
import stat
from unittest import mock

import pytest

from kanon_cli.repo import platform_utils
from kanon_cli.repo.project import _LinkFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_link_file(worktree, src_rel, topdir, dest_rel):
    """Return a _LinkFile instance for the given paths.

    Args:
        worktree: Absolute path to the git project checkout.
        src_rel: Source path relative to worktree.
        topdir: Absolute path to the top of the repo client checkout.
        dest_rel: Destination path relative to topdir.

    Returns:
        A _LinkFile instance configured with the provided paths.
    """
    return _LinkFile(worktree, src_rel, topdir, dest_rel)


# ---------------------------------------------------------------------------
# AC-TEST-001 -- Regression: OSError propagates; bare except does not swallow
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_linkfile_oserror_propagates_not_swallowed(tmp_path):
    """AC-TEST-001: OSError from symlink creation must propagate, not be silently swallowed.

    This test reproduces the exact bug condition from E0-F6-S1-T2: a _LinkFile
    whose __linkIt encounters an OSError during platform_utils.symlink(). Before
    the fix, the bare except OSError clause caught the exception and returned
    normally, leaving the caller unaware the symlink was never created.

    After the fix, the OSError is re-raised with source and destination context
    so callers can detect the failure.

    If this test fails with no exception raised (i.e., _Link() returns normally),
    the E0-F6-S1-T2 bug has regressed: the bare-except-without-reraise pattern
    has been reintroduced into _LinkFile.__linkIt in project.py.

    Arrange: Create a source file and a _LinkFile pointing to a destination.
    Patch platform_utils.symlink to raise OSError.
    Act: Call _Link().
    Assert: OSError propagates out of _Link() -- it is not swallowed.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "hello.txt"
    src_file.write_text("hello", encoding="utf-8")

    lf = _make_link_file(str(worktree), "hello.txt", str(topdir), "link-dest.txt")

    def _fail_symlink(src, dest):
        raise OSError(13, "Permission denied", dest)

    with mock.patch.object(platform_utils, "symlink", side_effect=_fail_symlink):
        try:
            lf._Link()
        except OSError:
            pass
        else:
            pytest.fail(
                "E0-F6-S1-T2 regression: _LinkFile._Link() returned normally when "
                "platform_utils.symlink() raised OSError. The bare-except-without-reraise "
                "pattern has been reintroduced into _LinkFile.__linkIt in project.py. "
                "The OSError must propagate so callers are not silently left with a "
                "missing symlink."
            )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Regression: exact E0-F6-S1-T2 bug condition triggered
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "exc_class,errno_val,strerror,test_id",
    [
        (OSError, 13, "Permission denied", "permission_denied"),
        (PermissionError, 13, "Permission denied", "permission_error_subclass"),
        (FileNotFoundError, 2, "No such file or directory", "file_not_found"),
        (OSError, 28, "No space left on device", "no_space"),
        (OSError, 17, "File exists", "file_exists"),
    ],
)
def test_exact_bug_condition_all_oserror_variants_propagate(
    tmp_path,
    exc_class,
    errno_val,
    strerror,
    test_id,
):
    """AC-TEST-002: All OSError variants from the original bug condition propagate.

    Verifies the exact bug condition: any OSError raised by platform_utils.symlink()
    must not be caught and swallowed. The parametrized inputs cover the full range
    of OSError subclasses that triggered silent swallowing in E0-F6-S1-T2.

    Before the fix, every variant below returned normally from _Link() without
    raising, leaving the caller's workspace with a missing symlink and no
    diagnostic information.

    If any parametrized case raises no exception, the regression is confirmed:
    the bare-except-without-reraise pattern has been reintroduced for that
    specific errno value.
    """
    worktree = tmp_path / f"project-{test_id}"
    worktree.mkdir()
    topdir = tmp_path / f"checkout-{test_id}"
    topdir.mkdir()

    src_file = worktree / "config.yaml"
    src_file.write_text("key: value", encoding="utf-8")

    lf = _make_link_file(
        str(worktree),
        "config.yaml",
        str(topdir),
        "linked-config.yaml",
    )

    def _raise(src, dest):
        raise exc_class(errno_val, strerror, dest)

    with mock.patch.object(platform_utils, "symlink", side_effect=_raise):
        with pytest.raises(OSError, match="Cannot link file"):
            lf._Link()


# ---------------------------------------------------------------------------
# AC-TEST-003 -- Guard: raise-with-chaining is structurally present in source
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_linkfile_raise_with_chaining_present_in_source():
    """AC-TEST-003: The raise-with-chaining OSError guard is in _LinkFile.__linkIt source.

    Inspects the source of _LinkFile._LinkFile__linkIt (the name-mangled form of
    __linkIt) to confirm that:
    - An OSError is caught by name (not a bare except clause).
    - A raise statement re-raises with context (not just a log-and-return).
    - Exception chaining via 'from e' is present.

    If any check fails, the raise-with-chaining guard has been removed from
    project.py and the E0-F6-S1-T2 bug would regress for any symlink failure.

    This test is complementary to the behavioral tests above: it makes the
    structural regression condition immediately obvious from the failure message
    even before a functional test runs.
    """
    source = inspect.getsource(_LinkFile._LinkFile__linkIt)

    assert "except OSError as e:" in source, (
        "E0-F6-S1-T2 regression guard: 'except OSError as e:' is no longer present "
        "in _LinkFile.__linkIt(). The named except clause that replaced the bare "
        "'except OSError:' has been removed. Restore the handler in "
        "src/kanon_cli/repo/project.py -- _LinkFile.__linkIt must catch OSError "
        "by name and re-raise it with context."
    )

    assert "raise OSError" in source, (
        "E0-F6-S1-T2 regression guard: 'raise OSError' is no longer present in "
        "_LinkFile.__linkIt(). The re-raise with source/destination context has been "
        "removed, restoring the silent-swallow behavior. Restore the raise statement "
        "in src/kanon_cli/repo/project.py -- _LinkFile.__linkIt must re-raise OSError "
        "with 'Cannot link file' context so callers are not silently left with a "
        "missing symlink."
    )

    assert "from e" in source, (
        "E0-F6-S1-T2 regression guard: exception chaining ('from e') is no longer "
        "present in _LinkFile.__linkIt(). The original OSError cause would be lost, "
        "making it harder to diagnose the root filesystem failure. Restore the "
        "'raise OSError(...) from e' pattern in src/kanon_cli/repo/project.py."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- Guard: PermissionError propagates with exception chaining
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_permission_error_propagates_with_exception_chaining(tmp_path):
    """AC-FUNC-001: PermissionError propagates from _Link() with chained cause.

    Verifies the guard prevents the E0-F6-S1-T2 bug from recurring for
    PermissionError specifically: the most common real-world failure mode
    when creating symlinks into read-only directories or under restricted
    permissions.

    The fix uses 'raise OSError(...) from e' which sets __cause__ to the
    original PermissionError. This test verifies the chain is intact so
    callers can inspect the root cause.

    If this test fails with __cause__ not being PermissionError, either:
    - The exception is silently swallowed (regression of E0-F6-S1-T2), or
    - The chaining was removed (making diagnostics harder).

    Arrange: Patch platform_utils.symlink to raise PermissionError.
    Act: Call _Link().
    Assert: OSError is raised; __cause__ is the original PermissionError.
    """
    worktree = tmp_path / "perm-project"
    worktree.mkdir()
    topdir = tmp_path / "perm-checkout"
    topdir.mkdir()

    src_file = worktree / "restricted.conf"
    src_file.write_text("restricted", encoding="utf-8")

    lf = _make_link_file(
        str(worktree),
        "restricted.conf",
        str(topdir),
        "linked-restricted.conf",
    )

    def _raise_permission(src, dest):
        raise PermissionError(13, "Permission denied", dest)

    with mock.patch.object(platform_utils, "symlink", side_effect=_raise_permission):
        with pytest.raises(OSError) as exc_info:
            lf._Link()

    raised = exc_info.value
    assert isinstance(raised.__cause__, PermissionError), (
        "E0-F6-S1-T2 regression: expected raised.__cause__ to be PermissionError "
        f"(confirming exception chaining via 'from e'), got: {type(raised.__cause__)!r}. "
        "The 'raise OSError(...) from e' in _LinkFile.__linkIt may have been "
        "replaced with a bare raise or a swallow. Restore the chained re-raise in "
        "src/kanon_cli/repo/project.py."
    )


@pytest.mark.unit
def test_linkfile_error_message_contains_source_and_dest_paths(tmp_path):
    """AC-FUNC-001: The propagated OSError message includes source and dest paths.

    The fix adds path context to the error message so operators can immediately
    identify which symlink failed without grepping the codebase. Verify the
    message format 'Cannot link file <src> to <dest>' is intact.

    If this test fails with the paths absent from the error message, the context
    has been removed from the raise statement in _LinkFile.__linkIt and the
    diagnostic value of the error is lost.
    """
    worktree = tmp_path / "ctx-project"
    worktree.mkdir()
    topdir = tmp_path / "ctx-checkout"
    topdir.mkdir()

    src_file = worktree / "important.yaml"
    src_file.write_text("important: true", encoding="utf-8")

    lf = _make_link_file(
        str(worktree),
        "important.yaml",
        str(topdir),
        "linked-important.yaml",
    )

    def _fail(src, dest):
        raise OSError(13, "Permission denied", dest)

    with mock.patch.object(platform_utils, "symlink", side_effect=_fail):
        with pytest.raises(OSError) as exc_info:
            lf._Link()

    raised = exc_info.value
    parts = []
    ex = raised
    while ex is not None:
        parts.append(str(ex))
        ex = ex.__cause__ or ex.__context__
        if ex is raised:
            break
    combined = " ".join(parts)

    assert "important.yaml" in combined, (
        "E0-F6-S1-T2 regression: source path 'important.yaml' not found in the "
        "propagated OSError message chain. The context added by the fix "
        "('Cannot link file <relSrc> to <absDest>') may have been removed. "
        f"Full error chain: {combined!r}"
    )
    assert "linked-important.yaml" in combined or str(topdir) in combined, (
        "E0-F6-S1-T2 regression: destination path not found in the propagated "
        "OSError message chain. The context added by the fix may have been removed. "
        f"Full error chain: {combined!r}"
    )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001 -- No stdout leakage on OSError
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_linkfile_oserror_does_not_leak_to_stdout(tmp_path, capsys):
    """AC-CHANNEL-001: OSError from _LinkFile._Link() must not produce stdout output.

    stdout is reserved for machine-consumable output. Error conditions must
    propagate via exceptions and reach stderr only through the top-level CLI
    handler. Verifies that no print() call inside __linkIt or _Link() writes
    to stdout when an OSError occurs.

    If this test fails with stdout content, a print() or sys.stdout.write()
    has been added inside the error path of _LinkFile (a channel discipline
    violation).

    Arrange: Patch platform_utils.symlink to raise OSError.
    Act: Call _Link(), catch the expected OSError.
    Assert: stdout captured by capsys is empty.
    """
    worktree = tmp_path / "chan-project"
    worktree.mkdir()
    topdir = tmp_path / "chan-checkout"
    topdir.mkdir()

    src_file = worktree / "data.txt"
    src_file.write_text("data", encoding="utf-8")

    lf = _make_link_file(
        str(worktree),
        "data.txt",
        str(topdir),
        "linked-data.txt",
    )

    def _fail(src, dest):
        raise OSError(13, "Permission denied", dest)

    with mock.patch.object(platform_utils, "symlink", side_effect=_fail):
        with pytest.raises(OSError):
            lf._Link()

    captured = capsys.readouterr()
    assert captured.out == "", (
        "E0-F6-S1-T2 channel discipline violation: _LinkFile._Link() produced stdout "
        f"output when OSError occurred. stdout content: {captured.out!r}. "
        "Error output must propagate as an exception, not be written to stdout."
    )


# ---------------------------------------------------------------------------
# Integration: real read-only directory confirms end-to-end behavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_linkfile_real_readonly_directory_raises_oserror(tmp_path):
    """AC-FUNC-001 / real filesystem: symlink into a read-only directory raises OSError.

    Uses a real filesystem operation (chmod to remove write bit) to confirm
    end-to-end behavior without any mocking. This exercises the full __linkIt
    code path with a genuine PermissionError from the OS.

    Arrange: Create a source file and make the destination directory read-only.
    Act: Call _Link() targeting a path inside the read-only directory.
    Assert: OSError propagates with source path in the message.

    The destination directory is restored to writable after the test to allow
    tmp_path cleanup to succeed.
    """
    worktree = tmp_path / "ro-project"
    worktree.mkdir()
    topdir = tmp_path / "ro-checkout"
    topdir.mkdir()

    src_file = worktree / "data.txt"
    src_file.write_text("data", encoding="utf-8")

    # Make topdir read-only so the symlink creation fails with PermissionError.
    topdir.chmod(stat.S_IRUSR | stat.S_IXUSR)

    lf = _make_link_file(str(worktree), "data.txt", str(topdir), "linked-data.txt")

    try:
        with pytest.raises(OSError) as exc_info:
            lf._Link()
    finally:
        # Restore write permission so tmp_path cleanup succeeds.
        topdir.chmod(stat.S_IRWXU)

    raised = exc_info.value
    parts = []
    ex = raised
    while ex is not None:
        parts.append(str(ex))
        ex = ex.__cause__ or ex.__context__
        if ex is raised:
            break
    combined = " ".join(parts)

    assert "data.txt" in combined or str(topdir) in combined, (
        "E0-F6-S1-T2 regression (real filesystem): expected the propagated OSError "
        "to contain source or destination path context, but the message chain did not. "
        f"Full error chain: {combined!r}"
    )
