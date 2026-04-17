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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_link_file(worktree, src_rel, topdir, dest_rel):
    """Return a _LinkFile instance for the given paths."""
    return project._LinkFile(str(worktree), src_rel, str(topdir), dest_rel)


# ---------------------------------------------------------------------------
# AC-TEST-005 -- Exception raised when glob destination is an existing file
# ---------------------------------------------------------------------------


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

    # Create source directory with matching files.
    src_dir = worktree / "configs"
    src_dir.mkdir()
    (src_dir / "app.xml").write_text("<config/>", encoding="utf-8")

    # Create dest as a regular file (not a directory) -- this is the bug condition.
    dest_file = topdir / "dest_as_file"
    dest_file.write_text("I am a file, not a directory", encoding="utf-8")

    lf = _make_link_file(worktree, "configs/*.xml", topdir, "dest_as_file")

    with pytest.raises((ManifestInvalidPathError, FileExistsError, ValueError, OSError)):
        lf._Link()


# ---------------------------------------------------------------------------
# AC-TEST-006 -- Error message includes the destination path
# ---------------------------------------------------------------------------


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

    # Create source directory with matching files.
    src_dir = worktree / "templates"
    src_dir.mkdir()
    (src_dir / "base.xml").write_text("<template/>", encoding="utf-8")

    # Destination as a regular file -- triggers the bug.
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


# ---------------------------------------------------------------------------
# Regression: directory destination works normally (no exception)
# ---------------------------------------------------------------------------


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

    # Create source directory with matching files.
    src_dir = worktree / "configs"
    src_dir.mkdir()
    (src_dir / "app.xml").write_text("<config/>", encoding="utf-8")

    # Create dest as a directory -- the valid case.
    dest_dir = topdir / "dest_dir"
    dest_dir.mkdir()

    lf = _make_link_file(worktree, "configs/*.xml", topdir, "dest_dir")

    # Must not raise -- directory dest is valid for glob src.
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

    # Create source directory with matching files.
    src_dir = worktree / "configs"
    src_dir.mkdir()
    (src_dir / "app.xml").write_text("<config/>", encoding="utf-8")

    # dest_dir does NOT exist -- _Link() should create it.
    lf = _make_link_file(worktree, "configs/*.xml", topdir, "new_dest_dir")

    # Must not raise -- a new dest directory is a valid case.
    lf._Link()
