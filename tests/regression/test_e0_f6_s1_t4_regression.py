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

"""Regression guard for E0-F6-S1-T4: symlink overwrite without warning.

Bug reference: E0-F6-S1-T4 -- project.py _LinkFile.__linkIt removed and
replaced an existing symlink without warning, even when the existing symlink
pointed to a foreign (non-repo-managed) target that the user had created
manually.

Root cause: project.py _LinkFile.__linkIt lines 452-463 -- the condition
``if not platform_utils.islink(absDest) or (platform_utils.readlink(absDest) != relSrc)``
triggered removal and replacement without checking whether the existing symlink
was repo-managed (pointing to relSrc) or foreign (pointing to a user-created
path). No warning was issued before overwriting a foreign symlink.

Fix (landed in E0-F6-S1-T4): Before removing an existing symlink, the code
reads its current target with platform_utils.readlink(). If the target differs
from relSrc (foreign symlink), logger.warning() is called with the destination
path, old target, and new repo-managed target. The symlink is still overwritten
in all cases -- the fix does not block sync.

This regression guard asserts that:
1. Overwriting a foreign symlink emits a logger.warning() call.
2. The warning message contains the old (foreign) target path.
3. Overwriting a repo-managed symlink does NOT emit a warning.
4. The symlink is replaced in all cases -- sync is never blocked.
5. The warning logic is structurally present in __linkIt source.
6. No stdout leakage occurs during symlink replacement operations.
"""

import inspect
import os
from unittest import mock

import pytest

from kanon_cli.repo.project import _LinkFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_link_file(worktree, src_rel, topdir, dest_rel):
    """Return a _LinkFile instance for the given paths.

    Args:
        worktree: Absolute path to the git project checkout (str or Path).
        src_rel: Source path relative to worktree (str).
        topdir: Absolute path to the top of the repo client checkout (str or Path).
        dest_rel: Destination path relative to topdir (str).

    Returns:
        A _LinkFile instance configured with the provided paths.
    """
    return _LinkFile(str(worktree), src_rel, str(topdir), dest_rel)


def _create_symlink_at(dest_path, target):
    """Create a symlink at dest_path pointing to target.

    Creates parent directories as needed.

    Args:
        dest_path: pathlib.Path for the symlink destination.
        target: str target for the symlink.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, str(dest_path))


# ---------------------------------------------------------------------------
# AC-TEST-001 -- Regression: foreign symlink overwrite emits a warning
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_foreign_symlink_overwrite_emits_warning(tmp_path):
    """AC-TEST-001: Overwriting a foreign symlink must produce a logger.warning call.

    This test reproduces the exact bug condition from E0-F6-S1-T4: a symlink at
    the destination path points to a foreign target (not the repo-managed relSrc).
    Before the fix, __linkIt removed and replaced the symlink silently. After the
    fix, __linkIt must call logger.warning() before replacing it.

    If this test fails (warning not called), the Bug 4 regression is confirmed:
    the warning logic in __linkIt has been removed or bypassed.

    Arrange: Create a symlink at dest pointing to a non-repo-managed foreign path.
    Act: Call _Link(). Capture logger.warning calls.
    Assert: logger.warning is called at least once.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "config.yaml"
    src_file.write_text("key: value", encoding="utf-8")

    foreign_target = "/usr/local/share/foreign-config.yaml"
    dest_path = topdir / "config.yaml"
    _create_symlink_at(dest_path, foreign_target)

    lf = _make_link_file(worktree, "config.yaml", topdir, "config.yaml")

    with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
        lf._Link()
        assert mock_logger.warning.called, (
            "E0-F6-S1-T4 regression: logger.warning was not called when a foreign "
            "symlink was replaced. The warning logic in project.py _LinkFile.__linkIt "
            "that checks for a foreign target before overwriting has been removed or "
            "bypassed. Restore the foreign-symlink warning block in __linkIt."
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "foreign_target,src_rel",
    [
        ("/home/user/.config/app.conf", "app.conf"),
        ("/opt/legacy/data/schema.json", "schemas/schema.json"),
        ("../../../some/other/path/build.xml", "build.xml"),
    ],
    ids=["home_dir_target", "opt_target", "relative_foreign_target"],
)
def test_foreign_symlink_overwrite_emits_warning_for_any_foreign_target(
    tmp_path,
    foreign_target,
    src_rel,
):
    """AC-TEST-001 (parametrized): Warning is emitted for any non-repo-managed foreign target.

    The foreign-symlink warning must fire regardless of the shape of the old
    target -- absolute paths, relative paths outside the repo root, and partial
    paths must all trigger the warning when they differ from relSrc.

    If any variant fails (warning not called), the Bug 4 regression is confirmed
    for that foreign target shape: the warning condition in __linkIt was made
    too restrictive (e.g., only checking absolute paths) or removed entirely.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    parts = src_rel.split("/")
    src_dir = worktree
    for part in parts[:-1]:
        src_dir = src_dir / part
        src_dir.mkdir(parents=True, exist_ok=True)
    src_file = src_dir / parts[-1]
    src_file.write_text("content", encoding="utf-8")

    dest_path = topdir / src_rel
    _create_symlink_at(dest_path, foreign_target)

    lf = _make_link_file(worktree, src_rel, topdir, src_rel)

    with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
        lf._Link()
        assert mock_logger.warning.called, (
            f"E0-F6-S1-T4 regression [foreign_target={foreign_target!r}]: "
            f"logger.warning was not called when foreign symlink was replaced. "
            f"The warning condition in __linkIt may be too restrictive or absent."
        )


# ---------------------------------------------------------------------------
# AC-TEST-002 -- Regression: exact E0-F6-S1-T4 bug condition triggered
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_exact_bug_condition_warning_includes_old_target(tmp_path):
    """AC-TEST-002: Exact bug condition -- warning message must include the old foreign target.

    Triggers the precise scenario described in E0-F6-S1-T4: a user has manually
    created a symlink at a path that the repo also manages. When repo syncs
    (_Link is called), it must warn the user by including the old target in the
    warning message so they know what was replaced.

    If this test fails (old target not in warning args), the Bug 4 regression is
    confirmed: the warning was logged without actionable information, or no warning
    was logged at all.

    Arrange: Create a foreign symlink at the destination with a distinctive path.
    Act: Call _Link(). Capture warning calls.
    Assert: The old foreign target appears in the warning call arguments.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "settings.conf"
    src_file.write_text("setting=value", encoding="utf-8")

    foreign_target = "/etc/myapp/custom-settings.conf"
    dest_path = topdir / "settings.conf"
    _create_symlink_at(dest_path, foreign_target)

    lf = _make_link_file(worktree, "settings.conf", topdir, "settings.conf")

    with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
        lf._Link()

    assert mock_logger.warning.called, (
        "E0-F6-S1-T4 regression: logger.warning was not called when foreign symlink "
        "was overwritten. The user must be warned before their symlink is replaced."
    )

    all_warning_text = " ".join(str(arg) for call in mock_logger.warning.call_args_list for arg in call.args)
    assert foreign_target in all_warning_text, (
        f"E0-F6-S1-T4 regression: The old foreign target {foreign_target!r} does not "
        f"appear in the warning message. The user must know what was replaced. "
        f"Got warning args: {all_warning_text!r}"
    )


@pytest.mark.unit
def test_exact_bug_condition_symlink_overwritten_not_blocked(tmp_path):
    """AC-TEST-002: Exact bug condition -- sync must complete; symlink must be replaced.

    The original Bug 4 description states the fix must NOT block sync: the
    symlink must still be overwritten even when a warning is emitted. If sync
    is blocked after the fix, the fix overcorrected and is itself a regression.

    Arrange: Create a foreign symlink at dest.
    Act: Call _Link().
    Assert: The symlink at dest now points to the repo-managed relSrc (not foreign).
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "data.bin"
    src_file.write_text("binary-ish", encoding="utf-8")

    foreign_target = "/var/run/old-data.bin"
    dest_path = topdir / "data.bin"
    _create_symlink_at(dest_path, foreign_target)

    lf = _make_link_file(worktree, "data.bin", topdir, "data.bin")
    lf._Link()

    assert os.path.islink(str(dest_path)), (
        "E0-F6-S1-T4 regression: dest is no longer a symlink after _Link(). "
        "The foreign-symlink fix must still create the repo-managed symlink."
    )
    actual_target = os.readlink(str(dest_path))
    expected_rel = os.path.relpath(str(worktree / "data.bin"), str(topdir))
    assert actual_target == expected_rel, (
        f"E0-F6-S1-T4 regression: after _Link(), the symlink target is {actual_target!r} "
        f"but expected the repo-managed target {expected_rel!r}. Sync was blocked or the "
        f"symlink was not replaced as required."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003 -- Guard: fixed code passes for current correct behavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_repo_managed_symlink_replaced_without_warning(tmp_path):
    """AC-TEST-003: Repo-managed symlink replacement must NOT produce a warning.

    A symlink that already points to the expected repo-managed relSrc is a
    no-op for __linkIt (same target -- no change needed). This path must not
    log a warning: the warning is reserved for foreign (user-created) symlinks.

    If this test fails (warning is called for a repo-managed symlink), the fix
    has been over-applied and is producing false-positive warnings on every
    repo sync where the symlink already points to the correct target.

    Arrange: Create a symlink at dest that already points to the exact relSrc
    that _Link() will compute.
    Act: Call _Link(). Capture warning calls.
    Assert: logger.warning is NOT called.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "managed.txt"
    src_file.write_text("managed content", encoding="utf-8")

    # Compute the exact relSrc that _Link() will use so the symlink looks repo-managed.
    expected_rel = os.path.relpath(str(src_file), str(topdir))
    dest_path = topdir / "managed.txt"
    _create_symlink_at(dest_path, expected_rel)

    lf = _make_link_file(worktree, "managed.txt", topdir, "managed.txt")

    with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
        lf._Link()
        assert not mock_logger.warning.called, (
            f"E0-F6-S1-T4 regression guard: logger.warning was called for a repo-managed "
            f"symlink that already points to the correct target. No warning should be "
            f"produced when the existing symlink is already correct. "
            f"warning call args: {mock_logger.warning.call_args_list!r}"
        )


@pytest.mark.unit
def test_warning_logic_structurally_present_in_linkit_source() -> None:
    """AC-TEST-003: The foreign-symlink warning block is structurally present in __linkIt.

    Inspects the source of _LinkFile.__linkIt to confirm the warning logic
    is intact. If the warning check is removed, any future sync will silently
    overwrite user-created symlinks without notification -- reproducing Bug 4.

    Checks for:
    - A call to logger.warning inside __linkIt.
    - A readlink() call to read the existing symlink target before comparison.
    - An islink() call to gate the warning on the symlink being present.

    If any check fails, the structural guard against Bug 4 has been removed.
    """
    # _LinkFile.__linkIt is name-mangled to _LinkFile__linkIt.
    method = getattr(_LinkFile, "_LinkFile__linkIt", None)
    assert method is not None, (
        "E0-F6-S1-T4 regression guard: _LinkFile.__linkIt is not accessible as "
        "_LinkFile__linkIt. The method may have been renamed or removed. "
        "The foreign-symlink warning logic lives in __linkIt."
    )

    source = inspect.getsource(method)

    assert "logger.warning" in source, (
        "E0-F6-S1-T4 regression guard: 'logger.warning' is not present in "
        "_LinkFile.__linkIt source. The foreign-symlink warning has been removed. "
        "Restore the warning call in project.py _LinkFile.__linkIt before overwriting "
        "an existing symlink that points to a non-repo-managed target."
    )

    assert "readlink" in source, (
        "E0-F6-S1-T4 regression guard: 'readlink' is not present in _LinkFile.__linkIt "
        "source. The code that reads the existing symlink's target before comparison has "
        "been removed. Without readlink(), the foreign-target check cannot function. "
        "Restore the readlink() call in project.py _LinkFile.__linkIt."
    )

    assert "islink" in source, (
        "E0-F6-S1-T4 regression guard: 'islink' is not present in _LinkFile.__linkIt "
        "source. The guard that checks whether an existing path is a symlink before "
        "reading its target has been removed. Restore the islink() gate in "
        "project.py _LinkFile.__linkIt."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001 -- Guard: full lifecycle reproduces the E0-F6-S1-T4 scenario
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_full_lifecycle_foreign_symlink_warned_and_replaced(tmp_path):
    """AC-FUNC-001: Full lifecycle -- foreign symlink triggers warning and is replaced.

    Reproduces the complete scenario from E0-F6-S1-T4: a user manually creates
    a symlink at a path the repo also manages. When repo syncs, it must:
    1. Warn the user that their symlink is being replaced (old target in message).
    2. Replace the symlink with the repo-managed target (sync proceeds).

    If either assertion fails, the Bug 4 guard has regressed: either the warning
    is silent (no user notification) or sync is blocked (symlink not replaced).
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "generated.xml"
    src_file.write_text("<root/>", encoding="utf-8")

    foreign_target = "/home/developer/my-symlinks/generated.xml"
    dest_path = topdir / "generated.xml"
    _create_symlink_at(dest_path, foreign_target)

    repo_managed_rel = "generated.xml"
    lf = _make_link_file(worktree, repo_managed_rel, topdir, "generated.xml")

    with mock.patch("kanon_cli.repo.project.logger") as mock_logger:
        lf._Link()

    # Warning must have been emitted.
    assert mock_logger.warning.called, (
        "E0-F6-S1-T4 regression: logger.warning was not called when foreign symlink "
        f"{foreign_target!r} was replaced during sync. The user must be notified."
    )

    # Warning args must include the old foreign target.
    all_warning_text = " ".join(str(arg) for call in mock_logger.warning.call_args_list for arg in call.args)
    assert foreign_target in all_warning_text, (
        f"E0-F6-S1-T4 regression: old foreign target {foreign_target!r} not in warning. Got: {all_warning_text!r}"
    )

    # Symlink must now point to the repo-managed target.
    expected_rel = os.path.relpath(str(worktree / repo_managed_rel), str(topdir))
    assert os.path.islink(str(dest_path)), (
        "E0-F6-S1-T4 regression: dest is not a symlink after _Link(). Sync was blocked."
    )
    assert os.readlink(str(dest_path)) == expected_rel, (
        f"E0-F6-S1-T4 regression: symlink target after _Link() is "
        f"{os.readlink(str(dest_path))!r}, expected {expected_rel!r}."
    )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001 -- stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_stdout_leakage_on_foreign_symlink_overwrite(
    tmp_path,
    capsys: pytest.CaptureFixture,
):
    """AC-CHANNEL-001: No stdout output when a foreign symlink is overwritten.

    stdout is reserved for machine-consumable output. The foreign-symlink warning
    must use logger.warning() (which routes to stderr via logging), never print()
    or sys.stdout.write(). Verifies that _Link() produces no stdout when
    overwriting a foreign symlink.

    If this test fails with non-empty stdout, a print() or sys.stdout.write()
    has been introduced into the foreign-symlink warning path -- a channel
    discipline violation.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "output.json"
    src_file.write_text("{}", encoding="utf-8")

    foreign_target = "/tmp/old-output.json"
    dest_path = topdir / "output.json"
    _create_symlink_at(dest_path, foreign_target)

    lf = _make_link_file(worktree, "output.json", topdir, "output.json")

    with mock.patch("kanon_cli.repo.project.logger"):
        lf._Link()

    captured = capsys.readouterr()
    assert captured.out == "", (
        f"E0-F6-S1-T4 channel discipline violation: _Link() produced stdout output "
        f"when overwriting a foreign symlink. stdout must be empty; warnings must use "
        f"logger.warning() not print(). stdout content: {captured.out!r}"
    )


@pytest.mark.unit
def test_no_stdout_leakage_on_repo_managed_symlink(
    tmp_path,
    capsys: pytest.CaptureFixture,
):
    """AC-CHANNEL-001: No stdout output when a repo-managed symlink is encountered.

    The no-op path (existing symlink already points to the correct target) must
    also produce no stdout output. Verifies that the no-op early-return in
    __linkIt is clean.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "checkout"
    topdir.mkdir()

    src_file = worktree / "schema.xsd"
    src_file.write_text("<schema/>", encoding="utf-8")

    expected_rel = os.path.relpath(str(src_file), str(topdir))
    dest_path = topdir / "schema.xsd"
    _create_symlink_at(dest_path, expected_rel)

    lf = _make_link_file(worktree, "schema.xsd", topdir, "schema.xsd")

    with mock.patch("kanon_cli.repo.project.logger"):
        lf._Link()

    captured = capsys.readouterr()
    assert captured.out == "", (
        f"E0-F6-S1-T4 channel discipline violation: _Link() produced stdout output "
        f"when encountering an already-correct repo-managed symlink. "
        f"stdout content: {captured.out!r}"
    )
