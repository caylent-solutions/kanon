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

"""Unit tests for Bug 2: linkfile errors silently swallowed.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 2 -- project.py __linkIt bare
except clause catches OSError and logs it without re-raising, silently
swallowing filesystem failures.

Root cause: project.py _LinkFile.__linkIt lines 462-463 -- bare except OSError
catches the exception, logs a message, and returns normally so callers never
know the symlink creation failed.

Fix: Remove the silent swallow. Re-raise the OSError with context (source path
and destination path) so permission errors, missing parent directories, and
other filesystem failures propagate to the caller.
"""

import stat
from unittest import mock

import pytest

from kanon_cli.repo import platform_utils
from kanon_cli.repo import project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_link_file(worktree, src_rel, topdir, dest_rel):
    """Return a _LinkFile instance for the given paths."""
    return project._LinkFile(worktree, src_rel, topdir, dest_rel)


# ---------------------------------------------------------------------------
# AC-TEST-001 -- Linkfile failure raises an exception with context
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_linkfile_oserror_raises_instead_of_being_swallowed(tmp_path):
    """AC-TEST-001: OSError from symlink creation must propagate, not be swallowed.

    Arrange: A _LinkFile whose __linkIt will hit an OSError because the
    destination directory does not exist and os.makedirs is patched to raise.
    Act: Call _Link().
    Assert: An OSError (or subclass) is raised -- not silently ignored.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "hello.txt"
    src_file.write_text("hello", encoding="utf-8")

    lf = _make_link_file(str(worktree), "hello.txt", str(topdir), "link-dest")

    def _fail_symlink(src, dest):
        raise OSError("simulated symlink failure")

    with mock.patch.object(platform_utils, "symlink", side_effect=_fail_symlink):
        with pytest.raises(OSError):
            lf._Link()


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Error message includes both source and destination paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_linkfile_error_message_includes_source_and_dest_paths(tmp_path):
    """AC-TEST-002: The raised OSError must reference both src and dest paths.

    Arrange: A _LinkFile configured with identifiable source and destination
    paths. Patch platform_utils.symlink to raise OSError.
    Act: Call _Link().
    Assert: The raised exception (or its __context__) carries both paths.
    """
    worktree = tmp_path / "my-project"
    worktree.mkdir()
    topdir = tmp_path / "client-checkout"
    topdir.mkdir()

    src_file = worktree / "config.yaml"
    src_file.write_text("key: value", encoding="utf-8")

    lf = _make_link_file(str(worktree), "config.yaml", str(topdir), "linked-config.yaml")

    def _fail_symlink(src, dest):
        raise OSError("simulated failure")

    with mock.patch.object(platform_utils, "symlink", side_effect=_fail_symlink):
        with pytest.raises(OSError) as exc_info:
            lf._Link()

    raised = exc_info.value
    # Collect all text from the exception chain.
    parts = []
    ex = raised
    while ex is not None:
        parts.append(str(ex))
        ex = ex.__cause__ or ex.__context__
        if ex is raised:
            break
    combined = " ".join(parts)

    assert "config.yaml" in combined, f"Expected 'config.yaml' in error message chain, got: {combined!r}"
    assert "linked-config.yaml" in combined or str(topdir) in combined, (
        f"Expected destination path in error message chain, got: {combined!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- PermissionError propagates with correct context
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_permission_error_propagates_from_linkfile(tmp_path):
    """AC-TEST-003: PermissionError (an OSError subclass) must propagate.

    Arrange: A directory where the destination parent is read-only so that
    os.makedirs raises PermissionError. Alternatively patch symlink directly.
    Act: Call _Link().
    Assert: PermissionError is raised (not caught and swallowed).
    """
    worktree = tmp_path / "perm-project"
    worktree.mkdir()
    topdir = tmp_path / "perm-checkout"
    topdir.mkdir()

    src_file = worktree / "secret.conf"
    src_file.write_text("secret", encoding="utf-8")

    lf = _make_link_file(str(worktree), "secret.conf", str(topdir), "linked-secret.conf")

    def _raise_permission_error(src, dest):
        raise PermissionError(13, "Permission denied", dest)

    with mock.patch.object(platform_utils, "symlink", side_effect=_raise_permission_error):
        with pytest.raises(OSError) as exc_info:
            lf._Link()

    # The raised exception must be an OSError whose cause is the original PermissionError.
    raised = exc_info.value
    assert isinstance(raised.__cause__, PermissionError), (
        f"Expected raised.__cause__ to be PermissionError, got: {type(raised.__cause__)!r}"
    )


# ---------------------------------------------------------------------------
# AC-CYCLE-001 -- Integration: real read-only destination raises OSError
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_linkfile_read_only_dest_directory_raises_oserror(tmp_path):
    """AC-CYCLE-001: Symlink into a read-only directory must raise, not silently fail.

    Arrange: Create a source file and a read-only destination directory.
    Act: Call _Link() targeting a path inside the read-only directory.
    Assert: An OSError is raised with source and destination context.

    This uses a real filesystem operation to confirm end-to-end behavior.
    The destination directory is restored to writable afterward for cleanup.
    """
    worktree = tmp_path / "ro-project"
    worktree.mkdir()
    topdir = tmp_path / "ro-checkout"
    topdir.mkdir()

    src_file = worktree / "data.txt"
    src_file.write_text("data", encoding="utf-8")

    # Make topdir read-only so the symlink creation fails.
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
        f"Expected source or destination path in error chain, got: {combined!r}"
    )


# ---------------------------------------------------------------------------
# Parametrized -- multiple OSError variants all propagate
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "exc_class,errno_val,strerror",
    [
        (OSError, 13, "Permission denied"),
        (PermissionError, 13, "Permission denied"),
        (FileNotFoundError, 2, "No such file or directory"),
        (OSError, 28, "No space left on device"),
    ],
    ids=["oserror_perm", "permission_error", "file_not_found", "no_space"],
)
def test_various_oserror_subclasses_propagate(tmp_path, exc_class, errno_val, strerror):
    """Various OSError subclasses from symlink creation must all propagate.

    Each variant is patched into platform_utils.symlink. In every case
    _Link() must raise -- not swallow the failure.
    """
    worktree = tmp_path / "proj"
    worktree.mkdir()
    topdir = tmp_path / "top"
    topdir.mkdir()

    src_file = worktree / "file.txt"
    src_file.write_text("content", encoding="utf-8")

    lf = _make_link_file(str(worktree), "file.txt", str(topdir), "linked-file.txt")

    def _raise(src, dest):
        raise exc_class(errno_val, strerror, dest)

    with mock.patch.object(platform_utils, "symlink", side_effect=_raise):
        with pytest.raises(OSError):
            lf._Link()
