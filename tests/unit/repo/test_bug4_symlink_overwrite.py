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

"""Unit tests for Bug 4: symlink overwrite without warning.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 4 -- project.py _LinkFile.__linkIt
removes and replaces an existing symlink without warning, even when the old
symlink points to a foreign (non-repo-managed) target.

Root cause: project.py _LinkFile.__linkIt lines 452-463 -- the condition
``if not platform_utils.islink(absDest) or (platform_utils.readlink(absDest) != relSrc)``
triggers removal and replacement without checking whether the existing symlink
was repo-managed (i.e. already pointing to relSrc) or foreign (user-created).
No warning is issued before overwriting a foreign symlink.

Fix: Before removing an existing symlink, read its current target with
platform_utils.readlink(). If the target differs from relSrc (foreign symlink),
log a warning that includes both the old target and the new target. Still
overwrite the symlink in all cases -- the fix must not block sync.
"""

import os
from unittest import mock

import pytest

from kanon_cli.repo import project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_link_file(worktree, src_rel, topdir, dest_rel):
    """Return a _LinkFile instance for the given paths."""
    return project._LinkFile(str(worktree), src_rel, str(topdir), dest_rel)


def _create_symlink_at(dest_path, target):
    """Create a symlink at dest_path pointing to target.

    Creates parent directories as needed.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, str(dest_path))


# ---------------------------------------------------------------------------
# AC-TEST-001 -- Repo-managed symlink replacement produces no warning
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_repo_managed_symlink_replaced_silently(tmp_path):
    """AC-TEST-001: Replacing a repo-managed symlink must produce no warning.

    A repo-managed symlink already points to the expected relSrc target.
    When __linkIt detects the symlink points to the correct target, it skips
    the update entirely (no-op). No warning is expected in this case.

    Arrange: Create a symlink at dest that already points to the same relSrc
    that _Link() would compute (os.path.relpath(src_abs, dest_dir)). This
    makes the symlink look repo-managed so __linkIt takes the no-op path.
    Act: Call _Link(). Capture any warning calls.
    Assert: logger.warning is NOT called.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "config.txt"
    src_file.write_text("content", encoding="utf-8")

    dest_path = topdir / "linked-config.txt"
    # _Link() computes: relpath = os.path.relpath(src_abs, os.path.dirname(dest_abs))
    # Pre-create the symlink with that exact target so it looks repo-managed.
    expected_rel = os.path.relpath(str(src_file), str(topdir))
    _create_symlink_at(dest_path, expected_rel)

    lf = _make_link_file(worktree, "config.txt", topdir, "linked-config.txt")

    with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
        lf._Link()
        mock_logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Foreign symlink replacement logs a warning
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_foreign_symlink_overwrite_logs_warning(tmp_path):
    """AC-TEST-002: Replacing a foreign symlink must log a warning.

    A foreign symlink points to an unrelated target (not the repo-managed
    relSrc). Before overwriting, the code must log a warning so the user
    knows their symlink was replaced.

    Arrange: Create a symlink at dest pointing to a foreign path (not relSrc).
    Act: Call _Link(). Capture any warning calls.
    Assert: logger.warning is called at least once.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "managed.txt"
    src_file.write_text("repo content", encoding="utf-8")

    dest_path = topdir / "linked.txt"
    foreign_target = "/some/user/created/symlink/target"
    _create_symlink_at(dest_path, foreign_target)

    lf = _make_link_file(worktree, "managed.txt", topdir, "linked.txt")

    with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
        lf._Link()
        mock_logger.warning.assert_called()


# ---------------------------------------------------------------------------
# AC-TEST-003 -- Warning message includes the old target path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_foreign_symlink_warning_includes_old_target(tmp_path):
    """AC-TEST-003: The warning message must include the old (foreign) target.

    When a foreign symlink is overwritten, the warning must reference the old
    target path so the user knows what was replaced.

    Arrange: Create a symlink pointing to a distinctive foreign target path.
    Act: Call _Link(). Capture warning calls.
    Assert: The warning arguments contain the old target path.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "repo-file.conf"
    src_file.write_text("repo config", encoding="utf-8")

    foreign_target = "/user/custom/location/foreign-target.conf"
    dest_path = topdir / "repo-file.conf"
    _create_symlink_at(dest_path, foreign_target)

    lf = _make_link_file(worktree, "repo-file.conf", topdir, "repo-file.conf")

    with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
        lf._Link()
        assert mock_logger.warning.called, "Expected logger.warning to be called for foreign symlink"

    # Collect all warning call args to check the foreign target appears.
    call_args_list = mock_logger.warning.call_args_list
    all_warning_text = " ".join(str(arg) for call in call_args_list for arg in call.args)
    assert foreign_target in all_warning_text, (
        f"Expected old target {foreign_target!r} in warning message, got warning args: {all_warning_text!r}"
    )


# ---------------------------------------------------------------------------
# Additional -- Symlink is overwritten in all cases (sync not blocked)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_foreign_symlink_is_still_replaced(tmp_path):
    """AC-FUNC-003: Symlink must be overwritten even when warning is logged.

    The warning must not block the sync. After _Link(), the destination
    symlink must point to the new repo-managed relSrc, regardless of whether
    it previously pointed to a foreign target.

    Arrange: Create a foreign symlink at dest.
    Act: Call _Link().
    Assert: dest now points to the repo-managed target (not the foreign one).
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "app.conf"
    src_file.write_text("app config", encoding="utf-8")

    foreign_target = "/old/foreign/path/app.conf"
    dest_path = topdir / "app.conf"
    _create_symlink_at(dest_path, foreign_target)

    lf = _make_link_file(worktree, "app.conf", topdir, "app.conf")
    lf._Link()

    # The symlink must now point to the repo-managed relative source.
    # _Link() computes relpath = os.path.relpath(src, os.path.dirname(dest)).
    expected_rel = os.path.relpath(str(worktree / "app.conf"), str(topdir))
    assert os.path.islink(str(dest_path)), "Expected dest to be a symlink after _Link()"
    new_target = os.readlink(str(dest_path))
    assert new_target == expected_rel, f"Expected symlink target to be {expected_rel!r}, got {new_target!r}"


@pytest.mark.unit
def test_repo_managed_symlink_is_unchanged(tmp_path):
    """AC-FUNC-001: Repo-managed symlink with correct target is left in place.

    When the existing symlink already points to the correct repo-managed path,
    the code must not modify it (no removal, no re-creation, no warning).

    Arrange: Create a symlink already pointing to the correct relSrc.
    Act: Call _Link().
    Assert: The symlink still exists and still points to relSrc.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "schema.json"
    src_file.write_text("{}", encoding="utf-8")

    rel_src = "schema.json"
    dest_path = topdir / "schema.json"
    _create_symlink_at(dest_path, rel_src)

    lf = _make_link_file(worktree, rel_src, topdir, "schema.json")
    lf._Link()

    # _Link() computes relpath = os.path.relpath(src, os.path.dirname(dest)).
    expected_rel = os.path.relpath(str(worktree / rel_src), str(topdir))
    assert os.path.islink(str(dest_path)), "Expected dest to remain a symlink"
    actual_target = os.readlink(str(dest_path))
    assert actual_target == expected_rel, f"Expected symlink target to be {expected_rel!r}, got {actual_target!r}"


# ---------------------------------------------------------------------------
# AC-CYCLE-001 -- Real sync lifecycle: foreign symlink at dest gets warning
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_foreign_symlink_lifecycle_warning_and_replacement(tmp_path):
    """AC-CYCLE-001: Full lifecycle -- foreign symlink triggers warning and is replaced.

    Simulates the scenario described in the bug report: a user manually creates
    a symlink at a path that repo also manages. When repo syncs, it must warn
    the user that their symlink is being replaced, then replace it.

    Arrange: Create a manual (foreign) symlink at the dest path.
    Act: Call _Link() (simulates repo_sync for that linkfile entry).
    Assert: Warning was logged with both old and new targets visible, and the
            final symlink points to the repo-managed path.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "generated.xml"
    src_file.write_text("<root/>", encoding="utf-8")

    foreign_target = "/home/user/manual-symlink/generated.xml"
    dest_path = topdir / "generated.xml"
    _create_symlink_at(dest_path, foreign_target)

    repo_managed_target = "generated.xml"

    lf = _make_link_file(worktree, repo_managed_target, topdir, "generated.xml")

    with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
        lf._Link()

    # Warning must have been logged.
    assert mock_logger.warning.called, "Expected logger.warning to be called when foreign symlink is replaced"

    # Warning args must include old and new targets.
    all_warning_text = " ".join(str(arg) for call in mock_logger.warning.call_args_list for arg in call.args)
    assert foreign_target in all_warning_text, (
        f"Expected old target {foreign_target!r} in warning, got: {all_warning_text!r}"
    )
    assert repo_managed_target in all_warning_text or str(worktree) in all_warning_text, (
        f"Expected new target in warning, got: {all_warning_text!r}"
    )

    # Symlink must now point to the repo-managed target.
    # _Link() computes relpath = os.path.relpath(src, os.path.dirname(dest)).
    expected_rel = os.path.relpath(str(worktree / repo_managed_target), str(topdir))
    assert os.readlink(str(dest_path)) == expected_rel, f"Expected symlink to be replaced with {expected_rel!r}"
