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

"""Unit tests for Bug 19: Glob source path with non-existent directory
produces a confusing or silent error.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 19 -- When linkfile src is a
glob pattern but the source directory does not exist, glob.glob() returns an
empty list silently. No meaningful error is raised.

Fix: Before calling glob.glob(), check os.path.exists() on the source
directory. If it does not exist, raise an error with a clear message including
the path that does not exist.
"""

import os

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
# AC-TEST-004 -- Clear error message when glob source path does not exist
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_nonexistent_glob_source_raises_error(tmp_path):
    """AC-TEST-004: When the glob source directory does not exist, _Link()
    must raise an exception with a clear error message including the missing path.

    The previous behavior was to silently call glob.glob() which would return
    an empty list when the source directory does not exist, resulting in no
    symlinks being created without any indication of the problem.

    Arrange: Create a _LinkFile with a glob src pattern pointing to a directory
    that does not exist.
    Act: Call _Link().
    Assert: An exception is raised that includes the non-existent source path.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    # The source uses a glob pattern (has_magic=True), but the base directory
    # does not exist.
    nonexistent_src_rel = "nonexistent_dir/*.xml"

    lf = _make_link_file(worktree, nonexistent_src_rel, topdir, "dest")

    with pytest.raises((ManifestInvalidPathError, FileNotFoundError, ValueError, OSError)) as exc_info:
        lf._Link()

    error_message = str(exc_info.value)
    # The error message must contain the non-existent source path or the
    # directory that was checked.
    nonexistent_dir = str(worktree / "nonexistent_dir")
    assert nonexistent_dir in error_message or "nonexistent_dir" in error_message, (
        f"Expected the error message to include the non-existent source path "
        f"{nonexistent_dir!r}, but got: {error_message!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "nonexistent_src",
    [
        "missing_dir/*.xml",
        "does/not/exist/*.conf",
    ],
    ids=["simple_missing_dir", "nested_missing_path"],
)
def test_nonexistent_glob_source_error_includes_path(tmp_path, nonexistent_src):
    """Each non-existent glob source pattern must produce an error mentioning the path.

    Parametrized over multiple missing source patterns to verify the error
    message consistently includes the missing directory path.

    Arrange: Create _LinkFile with a glob src pointing to a non-existent dir.
    Act: Call _Link().
    Assert: Exception is raised; error message includes the directory component.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    lf = _make_link_file(worktree, nonexistent_src, topdir, "dest")

    with pytest.raises((ManifestInvalidPathError, FileNotFoundError, ValueError, OSError)) as exc_info:
        lf._Link()

    error_message = str(exc_info.value)
    # At minimum the directory portion of the src must appear in the error.
    src_dir = os.path.dirname(nonexistent_src)
    assert src_dir in error_message or nonexistent_src in error_message, (
        f"Expected error message to include the missing source path component "
        f"{src_dir!r} or {nonexistent_src!r}, but got: {error_message!r}"
    )
