"""Unit tests for Bug 20: Glob linkfile silently skipped when dest is a file.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 20 -- When processing glob
linkfiles, if the destination path is an existing file (not a directory),
the code logs an error but continues execution without raising an exception.

Fix: When the destination is an existing file (not a directory), raise an
exception instead of logging and continuing. The error message must include
the destination path.
"""

import pytest

from kanon_cli.repo import project
from kanon_cli.repo.error import ManifestInvalidPathError


def _make_link_file(worktree, src_rel, topdir, dest_rel):
    """Return a _LinkFile instance for the given paths."""
    return project._LinkFile(str(worktree), src_rel, str(topdir), dest_rel)


@pytest.mark.unit
def test_glob_dest_file_raises_exception(tmp_path):
    """AC-TEST-005: When the glob destination is an existing file (not a
    directory), _Link() must raise an exception instead of logging and
    continuing.

    The previous behavior was to log an error and then silently skip all glob
    processing, leaving the caller unaware that nothing was linked.

    Arrange: Create a glob src pattern with matching files. Create dest as an
    existing regular file (not a directory).
    Act: Call _Link().
    Assert: An exception is raised.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_dir = worktree / "configs"
    src_dir.mkdir()
    (src_dir / "app.xml").write_text("<config/>", encoding="utf-8")

    dest_file = topdir / "dest_as_file"
    dest_file.write_text("I am a file, not a directory", encoding="utf-8")

    lf = _make_link_file(worktree, "configs/*.xml", topdir, "dest_as_file")

    with pytest.raises((ManifestInvalidPathError, FileExistsError, ValueError, OSError)):
        lf._Link()


@pytest.mark.unit
def test_glob_dest_file_error_includes_dest_path(tmp_path):
    """AC-TEST-006: The exception raised when glob destination is a file must
    include the destination path in the error message.

    A clear error message helps the user understand which path caused the
    problem and how to resolve it (e.g., remove the file so a directory can
    be created).

    Arrange: Create a glob src with matching files. Create dest as a file.
    Act: Call _Link().
    Assert: The raised exception's message includes the destination path.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_dir = worktree / "templates"
    src_dir.mkdir()
    (src_dir / "base.xml").write_text("<template/>", encoding="utf-8")

    dest_file = topdir / "my_dest_path"
    dest_file.write_text("blocking file content", encoding="utf-8")
    expected_dest_path = str(dest_file)

    lf = _make_link_file(worktree, "templates/*.xml", topdir, "my_dest_path")

    with pytest.raises((ManifestInvalidPathError, FileExistsError, ValueError, OSError)) as exc_info:
        lf._Link()

    error_message = str(exc_info.value)
    assert expected_dest_path in error_message or "my_dest_path" in error_message, (
        f"Expected the error message to include the destination path {expected_dest_path!r}, but got: {error_message!r}"
    )


@pytest.mark.unit
def test_glob_dest_directory_does_not_raise(tmp_path):
    """Regression: When the glob destination is a directory (correct case),
    _Link() must NOT raise an exception.

    This verifies the fix only applies to the file-as-dest case and does not
    accidentally reject valid directory destinations.

    Arrange: Create glob src with matching files. Create dest as a directory.
    Act: Call _Link().
    Assert: No exception is raised.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_dir = worktree / "configs"
    src_dir.mkdir()
    (src_dir / "app.xml").write_text("<config/>", encoding="utf-8")

    dest_dir = topdir / "dest_dir"
    dest_dir.mkdir()

    lf = _make_link_file(worktree, "configs/*.xml", topdir, "dest_dir")

    lf._Link()


@pytest.mark.unit
def test_glob_nonexistent_dest_does_not_raise(tmp_path):
    """When the glob destination does not yet exist, _Link() creates it and
    proceeds normally without raising an exception.

    Arrange: Create glob src with matching files. Do not create the dest path.
    Act: Call _Link().
    Assert: No exception is raised.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_dir = worktree / "configs"
    src_dir.mkdir()
    (src_dir / "app.xml").write_text("<config/>", encoding="utf-8")

    lf = _make_link_file(worktree, "configs/*.xml", topdir, "new_dest_dir")

    lf._Link()
