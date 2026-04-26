"""Integration tests for linkfile filesystem effects.

Tests cover actual on-disk behavior produced by _LinkFile._Link():
- AC-TEST-001: symlink creation (not a copy) for a regular file source
- AC-TEST-002: permissions preserved when reading through the symlink
- AC-TEST-003: atomic replacement of an existing symlink
- AC-TEST-004: absolute dest fork feature (dest given as absolute path)
- AC-TEST-005: exclude wildcard attribute filters children from per-child links

AC-FUNC-001: linkfile filesystem effects match the fork-specific documented behavior.
AC-CHANNEL-001: no stdout leakage on success or expected-error paths.
"""

import os
import pathlib
import stat

import pytest

from kanon_cli.repo.project import _LinkFile


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_linkfile(
    git_worktree: pathlib.Path,
    src: str,
    topdir: pathlib.Path,
    dest: str,
    exclude: str | None = None,
) -> _LinkFile:
    """Return a _LinkFile for the given paths.

    Args:
        git_worktree: Absolute path to the simulated project checkout.
        src: Source path relative to git_worktree (or absolute for absolute-dest tests).
        topdir: Absolute path to the simulated workspace root.
        dest: Destination path (relative to topdir, or absolute when testing fork feature).
        exclude: Optional comma-separated child names to omit.

    Returns:
        A configured _LinkFile instance.
    """
    kwargs = {}
    if exclude is not None:
        kwargs["exclude"] = exclude
    return _LinkFile(str(git_worktree), src, str(topdir), dest, **kwargs)


# ---------------------------------------------------------------------------
# AC-TEST-001: linkfile creates a symlink, not a copy
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_linkfile_creates_symlink_for_regular_file(tmp_path: pathlib.Path) -> None:
    """_Link() produces a symlink at dest, not a regular file copy.

    AC-TEST-001: the dest entry must be a symlink (os.path.islink returns True).
    This confirms that _LinkFile never copies the source bytes -- it only
    creates a filesystem symlink.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "config.txt"
    src_file.write_text("important config\n", encoding="utf-8")

    lf = _make_linkfile(worktree, "config.txt", topdir, "config.txt")
    lf._Link()

    dest = topdir / "config.txt"
    assert os.path.islink(str(dest)), (
        f"Expected a symlink at {dest} after _LinkFile._Link(), but islink() returned False. "
        f"The destination must be a symlink, not a copy of the source file."
    )
    assert not dest.is_file() or os.path.islink(str(dest)), f"Expected {dest} to be a symlink, not a regular file."


@pytest.mark.integration
def test_linkfile_symlink_resolves_to_source_content(tmp_path: pathlib.Path) -> None:
    """The symlink created by _Link() resolves to the source file's content.

    AC-TEST-001: reading through the symlink yields the original source bytes.
    This verifies that the symlink target is correctly computed relative to
    the destination directory.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    expected_content = "canonical source content for symlink resolution\n"
    src_file = worktree / "data.txt"
    src_file.write_text(expected_content, encoding="utf-8")

    lf = _make_linkfile(worktree, "data.txt", topdir, "data.txt")
    lf._Link()

    dest = topdir / "data.txt"
    assert os.path.islink(str(dest)), f"Expected {dest} to be a symlink."
    actual_content = dest.read_text(encoding="utf-8")
    assert actual_content == expected_content, (
        f"Expected symlink at {dest} to resolve to {expected_content!r} "
        f"but read {actual_content!r}. Symlink target: {os.readlink(str(dest))!r}"
    )


@pytest.mark.integration
def test_linkfile_does_not_create_regular_file(tmp_path: pathlib.Path) -> None:
    """After _Link(), the dest inode is a symlink, never a plain regular file.

    AC-TEST-001: explicitly verifies that os.path.islink is True and that the
    raw destination path (without dereferencing) is recognisable as a symlink
    entry via os.lstat, not as a regular file.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "manifest.xml"
    src_file.write_text("<manifest />\n", encoding="utf-8")

    lf = _make_linkfile(worktree, "manifest.xml", topdir, "manifest.xml")
    lf._Link()

    dest = topdir / "manifest.xml"
    dest_stat = os.lstat(str(dest))
    assert stat.S_ISLNK(dest_stat.st_mode), (
        f"Expected {dest} to be a symbolic link (lstat mode {dest_stat.st_mode:#o}) "
        f"but S_ISLNK returned False. _LinkFile must create a symlink, not copy the file."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002: linkfile permissions preserved
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_linkfile_preserves_source_permissions_via_symlink(tmp_path: pathlib.Path) -> None:
    """The symlink created by _Link() preserves the source file's permissions.

    AC-TEST-002: reading the source permissions through the symlink must yield
    the same mode bits as the original source file. Because symlinks themselves
    do not have meaningful permission bits on Linux (lstat mode is always 0o777
    for the link entry), the test checks that the resolved target retains its
    original mode.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "script.sh"
    src_file.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
    # Set a distinctive permission mask: owner-execute, group-read, world none.
    src_file.chmod(0o750)
    expected_mode = stat.S_IMODE(os.stat(str(src_file)).st_mode)

    lf = _make_linkfile(worktree, "script.sh", topdir, "script.sh")
    lf._Link()

    dest = topdir / "script.sh"
    assert os.path.islink(str(dest)), f"Expected {dest} to be a symlink after _Link()."
    # os.stat follows the symlink, so this reads the source file's mode.
    resolved_mode = stat.S_IMODE(os.stat(str(dest)).st_mode)
    assert resolved_mode == expected_mode, (
        f"Expected resolved permissions {expected_mode:#o} (from source) "
        f"but got {resolved_mode:#o} through the symlink at {dest}."
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "mode",
    [0o644, 0o755, 0o600, 0o700],
)
def test_linkfile_preserves_various_source_modes(tmp_path: pathlib.Path, mode: int) -> None:
    """Symlink resolves to source with the same permission bits for various modes.

    AC-TEST-002: parameterized over common Unix permission masks to confirm that
    _LinkFile does not alter the source file's mode when creating the symlink.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "target.bin"
    src_file.write_bytes(b"\x00\x01\x02\x03")
    src_file.chmod(mode)
    expected_mode = stat.S_IMODE(os.stat(str(src_file)).st_mode)

    lf = _make_linkfile(worktree, "target.bin", topdir, "link.bin")
    lf._Link()

    dest = topdir / "link.bin"
    assert os.path.islink(str(dest)), f"Expected a symlink at {dest} for mode {mode:#o}."
    resolved_mode = stat.S_IMODE(os.stat(str(dest)).st_mode)
    assert resolved_mode == expected_mode, (
        f"Mode {mode:#o}: expected resolved mode {expected_mode:#o} "
        f"but got {resolved_mode:#o} through symlink at {dest}."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003: linkfile replacement overwrites existing symlink atomically
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_linkfile_replaces_existing_symlink_pointing_to_stale_target(tmp_path: pathlib.Path) -> None:
    """_Link() overwrites an existing stale symlink with one pointing to the current source.

    AC-TEST-003: when the destination already exists as a symlink pointing
    elsewhere, _Link() must remove the stale entry and create a fresh symlink
    targeting the current source. The operation must succeed without error.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    current_src = worktree / "current.conf"
    current_src.write_text("current configuration\n", encoding="utf-8")

    stale_target = tmp_path / "stale.conf"
    stale_target.write_text("stale\n", encoding="utf-8")
    dest = topdir / "link.conf"
    os.symlink(str(stale_target), str(dest))
    assert os.path.islink(str(dest)), "Pre-condition: stale symlink must be in place before _Link()."

    lf = _make_linkfile(worktree, "current.conf", topdir, "link.conf")
    lf._Link()

    assert os.path.islink(str(dest)), (
        f"Expected {dest} to still be a symlink after replacement, but islink() returned False."
    )
    resolved_content = dest.read_text(encoding="utf-8")
    assert resolved_content == "current configuration\n", (
        f"Expected symlink to resolve to current source after replacement, "
        f"but got: {resolved_content!r}. Symlink target: {os.readlink(str(dest))!r}"
    )


@pytest.mark.integration
def test_linkfile_replacement_symlink_no_longer_points_to_stale_target(tmp_path: pathlib.Path) -> None:
    """After replacement, the dest symlink does not reference the old stale target.

    AC-TEST-003: the raw readlink() value after _Link() must not point at the
    stale target path. This confirms that the old entry was fully removed.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    current_src = worktree / "new.yaml"
    current_src.write_text("new: true\n", encoding="utf-8")

    stale_target = "/some/user/path/stale.yaml"
    dest = topdir / "link.yaml"
    os.symlink(stale_target, str(dest))

    lf = _make_linkfile(worktree, "new.yaml", topdir, "link.yaml")
    lf._Link()

    new_target = os.readlink(str(dest))
    assert new_target != stale_target, (
        f"Expected the symlink at {dest} to no longer point at the stale target "
        f"{stale_target!r}, but readlink() still returned {new_target!r}."
    )
    assert os.path.islink(str(dest)), f"Expected {dest} to be a symlink after replacement."


@pytest.mark.integration
def test_linkfile_idempotent_on_already_current_symlink(tmp_path: pathlib.Path) -> None:
    """Calling _Link() twice produces the same result as calling it once.

    AC-TEST-003: _Link() is idempotent -- when the destination symlink already
    points to the correct target, a second invocation leaves it unchanged and
    does not raise an error.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "settings.json"
    src_file.write_text('{"version": 1}\n', encoding="utf-8")

    lf = _make_linkfile(worktree, "settings.json", topdir, "settings.json")
    lf._Link()

    dest = topdir / "settings.json"
    first_target = os.readlink(str(dest))

    lf._Link()

    second_target = os.readlink(str(dest))
    assert second_target == first_target, (
        f"Expected idempotent _Link() to leave the symlink target unchanged "
        f"({first_target!r}), but the second call changed it to {second_target!r}."
    )
    assert dest.read_text(encoding="utf-8") == '{"version": 1}\n', (
        "Expected symlink content to remain correct after second _Link() call."
    )


# ---------------------------------------------------------------------------
# AC-TEST-004: linkfile absolute dest fork feature works
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_linkfile_absolute_dest_creates_symlink_at_absolute_path(tmp_path: pathlib.Path) -> None:
    """_Link() with an absolute dest path creates the symlink at that absolute path.

    AC-TEST-004: the absolute dest fork allows the symlink to be placed outside
    the workspace topdir. The resulting symlink must exist at the literal
    absolute dest path and must resolve to the source file's content.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "schema.json"
    src_file.write_text('{"schema": true}\n', encoding="utf-8")

    abs_dest = str(tmp_path / "absolute-link" / "schema.json")

    lf = _make_linkfile(worktree, "schema.json", topdir, abs_dest)
    lf._Link()

    assert os.path.islink(abs_dest), (
        f"Expected a symlink at the absolute dest path {abs_dest!r} after _Link(), but islink() returned False."
    )
    resolved = pathlib.Path(abs_dest).read_text(encoding="utf-8")
    assert resolved == '{"schema": true}\n', (
        f"Expected symlink at absolute dest {abs_dest!r} to resolve to source content, but read: {resolved!r}"
    )


@pytest.mark.integration
def test_linkfile_absolute_dest_is_actual_symlink_not_copy(tmp_path: pathlib.Path) -> None:
    """The entry at an absolute dest path is a symlink, not a file copy.

    AC-TEST-004: confirms that the fork that handles absolute dest paths still
    creates a symlink (not a copy) at the given absolute path.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "README.md"
    src_file.write_text("# project\n", encoding="utf-8")

    abs_dest = str(tmp_path / "out" / "README.md")

    lf = _make_linkfile(worktree, "README.md", topdir, abs_dest)
    lf._Link()

    dest_stat = os.lstat(abs_dest)
    assert stat.S_ISLNK(dest_stat.st_mode), (
        f"Expected lstat at {abs_dest!r} to show a symbolic link "
        f"(mode {dest_stat.st_mode:#o}), but S_ISLNK returned False."
    )


@pytest.mark.integration
def test_linkfile_absolute_dest_creates_parent_dirs(tmp_path: pathlib.Path) -> None:
    """_Link() with an absolute dest creates intermediate parent directories.

    AC-TEST-004: the absolute dest fork must call os.makedirs on the parent of
    the dest path so that deeply nested absolute destinations are supported.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "tool"
    src_file.write_text("#!/bin/sh\n", encoding="utf-8")

    abs_dest = str(tmp_path / "deep" / "nested" / "dir" / "tool")

    lf = _make_linkfile(worktree, "tool", topdir, abs_dest)
    lf._Link()

    assert os.path.islink(abs_dest), (
        f"Expected a symlink at {abs_dest!r} after _Link() with nested absolute dest, "
        f"but the path does not exist or is not a symlink."
    )


# ---------------------------------------------------------------------------
# AC-TEST-005: linkfile exclude wildcards work
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_linkfile_exclude_single_child(tmp_path: pathlib.Path) -> None:
    """exclude='tests' links all children of a directory except 'tests'.

    AC-TEST-005: when a directory source is given with exclude='tests', the
    resulting per-child symlinks must include every child except 'tests'.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_dir = worktree / "pkg"
    src_dir.mkdir()
    (src_dir / "src").mkdir()
    (src_dir / "tests").mkdir()
    (src_dir / "README.md").write_text("# pkg\n", encoding="utf-8")

    lf = _make_linkfile(worktree, "pkg", topdir, "linked-pkg", exclude="tests")
    lf._Link()

    dest_dir = topdir / "linked-pkg"
    assert dest_dir.is_dir(), f"Expected {dest_dir} to be a directory after per-child linking with exclude."
    assert os.path.islink(str(dest_dir / "src")), f"Expected 'src' symlink inside {dest_dir} after exclude='tests'."
    assert os.path.islink(str(dest_dir / "README.md")), (
        f"Expected 'README.md' symlink inside {dest_dir} after exclude='tests'."
    )
    assert not (dest_dir / "tests").exists(), (
        f"Expected 'tests' to be absent from {dest_dir} because it is in exclude='tests', but it was found."
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "exclude_value,excluded_names,linked_names",
    [
        ("tests", ["tests"], ["src", "lib"]),
        ("tests,docs", ["tests", "docs"], ["src", "lib"]),
        (" tests , docs ", ["tests", "docs"], ["src", "lib"]),
    ],
)
def test_linkfile_exclude_combinations(
    tmp_path: pathlib.Path,
    exclude_value: str,
    excluded_names: list[str],
    linked_names: list[str],
) -> None:
    """Parameterized: various exclude values produce correct include/exclude sets.

    AC-TEST-005: tests single name, multiple comma-separated names, and names
    with surrounding whitespace (which must be stripped before comparison).
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_dir = worktree / "pkg"
    src_dir.mkdir()
    for name in ["src", "lib", "tests", "docs"]:
        child = src_dir / name
        child.mkdir()
        (child / "marker.txt").write_text(f"{name}\n", encoding="utf-8")

    lf = _make_linkfile(worktree, "pkg", topdir, "linked-pkg", exclude=exclude_value)
    lf._Link()

    dest_dir = topdir / "linked-pkg"
    assert dest_dir.is_dir(), (
        f"Expected {dest_dir} to be a directory after per-child linking with exclude={exclude_value!r}."
    )
    for name in linked_names:
        assert os.path.islink(str(dest_dir / name)), (
            f"Expected symlink for {name!r} inside {dest_dir} when exclude={exclude_value!r}, but it was not found."
        )
    for name in excluded_names:
        assert not (dest_dir / name).exists(), (
            f"Expected {name!r} to be absent from {dest_dir} when exclude={exclude_value!r}, but it was found."
        )


@pytest.mark.integration
def test_linkfile_exclude_always_skips_dot_git(tmp_path: pathlib.Path) -> None:
    """_LinkWithExclude always omits .git even without an explicit exclude entry.

    AC-TEST-005: the built-in _LINKFILE_EXCLUDE_ALWAYS set includes '.git'.
    Even when exclude='' (empty) or a different name is given, .git is never
    linked into the dest directory.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_dir = worktree / "pkg"
    src_dir.mkdir()
    (src_dir / "src").mkdir()
    git_dir = src_dir / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    lf = _make_linkfile(worktree, "pkg", topdir, "linked-pkg", exclude="unrelated")
    lf._Link()

    dest_dir = topdir / "linked-pkg"
    assert os.path.islink(str(dest_dir / "src")), f"Expected 'src' symlink inside {dest_dir} but it was not found."
    assert not (dest_dir / ".git").exists(), (
        f"Expected '.git' to be absent from {dest_dir} because it is in _LINKFILE_EXCLUDE_ALWAYS, but it was found."
    )


@pytest.mark.integration
def test_linkfile_no_exclude_creates_single_directory_symlink(tmp_path: pathlib.Path) -> None:
    """Without an exclude attribute, _Link() creates one symlink to the whole directory.

    AC-TEST-005: the exclude feature is opt-in. When exclude is not given, the
    source directory is linked as a single entity (one symlink pointing at the
    whole directory), not as individual per-child symlinks.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_dir = worktree / "pkg"
    src_dir.mkdir()
    (src_dir / "src").mkdir()
    (src_dir / "lib").mkdir()

    lf = _make_linkfile(worktree, "pkg", topdir, "linked-pkg")
    lf._Link()

    dest = topdir / "linked-pkg"
    assert os.path.islink(str(dest)), (
        f"Expected {dest} to be a single directory symlink when no exclude is given, "
        f"but islink() returned False. Got: {os.lstat(str(dest))!r}"
    )
    assert (dest / "src").is_dir(), f"Expected 'src' to be accessible through the directory symlink at {dest}."
    assert (dest / "lib").is_dir(), f"Expected 'lib' to be accessible through the directory symlink at {dest}."


# ---------------------------------------------------------------------------
# AC-FUNC-001: filesystem effects match documented fork behavior
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_linkfile_relative_dest_resolved_under_topdir(tmp_path: pathlib.Path) -> None:
    """_Link() with a relative dest resolves it under topdir.

    AC-FUNC-001: the standard (non-absolute-dest) fork computes dest as
    <topdir>/<dest>. The resulting symlink must be placed inside topdir.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "values.yaml"
    src_file.write_text("env: production\n", encoding="utf-8")

    lf = _make_linkfile(worktree, "values.yaml", topdir, "helm/values.yaml")
    lf._Link()

    dest = topdir / "helm" / "values.yaml"
    assert os.path.islink(str(dest)), (
        f"Expected a symlink at {dest} (relative dest resolved under topdir) after _Link()."
    )
    assert dest.read_text(encoding="utf-8") == "env: production\n", "Expected symlink to resolve to source content."


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: no stdout leakage
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_linkfile_link_does_not_write_to_stdout(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
    """_Link() does not write any output to stdout on a successful invocation.

    AC-CHANNEL-001: library code must not print to stdout. All output must go
    through the logging system (stderr) or be suppressed.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "output.txt"
    src_file.write_text("data\n", encoding="utf-8")

    lf = _make_linkfile(worktree, "output.txt", topdir, "output.txt")
    lf._Link()

    captured = capsys.readouterr()
    assert not captured.out, f"Expected no stdout output from _LinkFile._Link(), but got: {captured.out!r}"
