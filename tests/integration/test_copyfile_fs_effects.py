"""Integration tests for copyfile filesystem effects.

Tests cover actual on-disk behavior produced by _CopyFile._Copy():
- AC-TEST-001: regular file creation (not a symlink)
- AC-TEST-002: source file permissions preserved in the copy
- AC-TEST-003: atomic replacement of an existing destination file

AC-FUNC-001: copyfile produces an actual filesystem copy (bytes on disk).
AC-CHANNEL-001: no stdout leakage on success paths.
"""

import os
import pathlib
import stat

import pytest

from kanon_cli.repo.project import _CopyFile


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_copyfile(
    git_worktree: pathlib.Path,
    src: str,
    topdir: pathlib.Path,
    dest: str,
) -> _CopyFile:
    """Return a _CopyFile for the given paths.

    Args:
        git_worktree: Absolute path to the simulated project checkout.
        src: Source path relative to git_worktree.
        topdir: Absolute path to the simulated workspace root.
        dest: Destination path relative to topdir.

    Returns:
        A configured _CopyFile instance.
    """
    return _CopyFile(str(git_worktree), src, str(topdir), dest)


# ---------------------------------------------------------------------------
# AC-TEST-001: copyfile creates a regular file (not a symlink)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_copyfile_creates_regular_file_not_symlink(tmp_path: pathlib.Path) -> None:
    """_Copy() produces a regular file at dest, not a symlink.

    AC-TEST-001: the dest entry must be a plain regular file.
    os.path.islink() must return False and os.path.isfile() must return True.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "config.txt"
    src_file.write_text("important config\n", encoding="utf-8")

    cf = _make_copyfile(worktree, "config.txt", topdir, "config.txt")
    cf._Copy()

    dest = topdir / "config.txt"
    assert dest.exists(), f"Expected a file at {dest} after _CopyFile._Copy(), but it does not exist."
    assert os.path.isfile(str(dest)), (
        f"Expected {dest} to be a regular file after _Copy(), but isfile() returned False."
    )
    assert not os.path.islink(str(dest)), (
        f"Expected {dest} to be a regular file, not a symlink. "
        f"_CopyFile._Copy() must copy bytes to disk, not create a symlink."
    )


@pytest.mark.integration
def test_copyfile_dest_is_regular_file_by_lstat(tmp_path: pathlib.Path) -> None:
    """lstat() on the dest produced by _Copy() reports a regular file.

    AC-TEST-001: explicitly checks the raw inode type via os.lstat so that
    symlinks that point to regular files do not satisfy the assertion.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "manifest.xml"
    src_file.write_text("<manifest />\n", encoding="utf-8")

    cf = _make_copyfile(worktree, "manifest.xml", topdir, "manifest.xml")
    cf._Copy()

    dest = topdir / "manifest.xml"
    dest_stat = os.lstat(str(dest))
    assert stat.S_ISREG(dest_stat.st_mode), (
        f"Expected {dest} to be a regular file (lstat mode {dest_stat.st_mode:#o}), "
        f"but S_ISREG returned False. _CopyFile must write a real file, not a symlink."
    )
    assert not stat.S_ISLNK(dest_stat.st_mode), (
        f"Expected {dest} not to be a symbolic link (lstat mode {dest_stat.st_mode:#o}), but S_ISLNK returned True."
    )


@pytest.mark.integration
def test_copyfile_dest_content_matches_source(tmp_path: pathlib.Path) -> None:
    """_Copy() produces a dest whose byte content is identical to the source.

    AC-TEST-001, AC-FUNC-001: reading the dest returns the same bytes as the
    original source file, confirming that a real filesystem copy was made.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    expected_content = "canonical source content for copy assertion\n"
    src_file = worktree / "data.txt"
    src_file.write_text(expected_content, encoding="utf-8")

    cf = _make_copyfile(worktree, "data.txt", topdir, "data.txt")
    cf._Copy()

    dest = topdir / "data.txt"
    assert not os.path.islink(str(dest)), f"Expected {dest} to be a regular file, not a symlink."
    actual_content = dest.read_text(encoding="utf-8")
    assert actual_content == expected_content, (
        f"Expected dest {dest} to contain {expected_content!r} "
        f"but read {actual_content!r}. _Copy() must produce an independent file copy."
    )


@pytest.mark.integration
def test_copyfile_dest_is_independent_of_source(tmp_path: pathlib.Path) -> None:
    """Modifying the source after _Copy() does not change the destination.

    AC-TEST-001, AC-FUNC-001: the copy is an independent file -- it has its own
    inode and is not a hard link or symlink to the source. Modifying the source
    after copying must not affect the previously copied destination.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    original_content = "original content\n"
    src_file = worktree / "values.yaml"
    src_file.write_text(original_content, encoding="utf-8")

    cf = _make_copyfile(worktree, "values.yaml", topdir, "values.yaml")
    cf._Copy()

    dest = topdir / "values.yaml"
    assert not os.path.islink(str(dest)), f"Expected {dest} to be a regular file, not a symlink."

    # Overwrite the source -- a real copy must not be affected.
    src_file.write_text("completely different content\n", encoding="utf-8")

    dest_content = dest.read_text(encoding="utf-8")
    assert dest_content == original_content, (
        f"Expected dest to retain original content {original_content!r} after source was overwritten, "
        f"but got {dest_content!r}. _Copy() must produce an independent file, not a symlink."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002: copyfile permissions preserved
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_copyfile_preserves_source_permissions(tmp_path: pathlib.Path) -> None:
    """_Copy() preserves the source file's permission bits in the destination.

    AC-TEST-002: shutil.copy (used internally) copies both content and mode
    bits. The dest file must report the same permission mask as the source.
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

    cf = _make_copyfile(worktree, "script.sh", topdir, "script.sh")
    cf._Copy()

    dest = topdir / "script.sh"
    assert not os.path.islink(str(dest)), f"Expected {dest} to be a regular file, not a symlink."
    dest_mode = stat.S_IMODE(os.stat(str(dest)).st_mode)
    assert dest_mode == expected_mode, (
        f"Expected dest permissions {expected_mode:#o} (copied from source) "
        f"but got {dest_mode:#o} at {dest}. _Copy() must use shutil.copy which preserves mode bits."
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "mode",
    [0o644, 0o755, 0o600, 0o700, 0o640],
)
def test_copyfile_preserves_various_source_modes(tmp_path: pathlib.Path, mode: int) -> None:
    """Parameterized: dest has the same permission bits as the source for various modes.

    AC-TEST-002: uses common Unix permission masks to confirm that _CopyFile
    preserves mode bits for read-only, executable, and restricted files.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "target.bin"
    src_file.write_bytes(b"\x00\x01\x02\x03")
    src_file.chmod(mode)
    expected_mode = stat.S_IMODE(os.stat(str(src_file)).st_mode)

    cf = _make_copyfile(worktree, "target.bin", topdir, "copy.bin")
    cf._Copy()

    dest = topdir / "copy.bin"
    assert not os.path.islink(str(dest)), f"Expected a regular file at {dest} for mode {mode:#o}."
    dest_mode = stat.S_IMODE(os.stat(str(dest)).st_mode)
    assert dest_mode == expected_mode, (
        f"Mode {mode:#o}: expected dest mode {expected_mode:#o} but got {dest_mode:#o} at {dest}."
    )


@pytest.mark.integration
def test_copyfile_read_only_source_permissions_preserved(tmp_path: pathlib.Path) -> None:
    """_Copy() preserves read-only source permissions in the destination.

    AC-TEST-002: specifically tests that a read-only source (mode 0o444) produces
    a read-only destination, confirming that _Copy() does not force write
    permissions on the output.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "readonly.txt"
    src_file.write_text("immutable content\n", encoding="utf-8")
    src_file.chmod(0o444)
    expected_mode = stat.S_IMODE(os.stat(str(src_file)).st_mode)

    cf = _make_copyfile(worktree, "readonly.txt", topdir, "readonly.txt")
    cf._Copy()

    dest = topdir / "readonly.txt"
    assert not os.path.islink(str(dest)), f"Expected {dest} to be a regular file, not a symlink."
    dest_mode = stat.S_IMODE(os.stat(str(dest)).st_mode)
    assert dest_mode == expected_mode, (
        f"Expected read-only mode {expected_mode:#o} preserved at {dest}, "
        f"but got {dest_mode:#o}. _Copy() must not alter permission bits."
    )

    # Restore write permission so tmp_path cleanup can remove the file.
    dest.chmod(0o644)
    src_file.chmod(0o644)


# ---------------------------------------------------------------------------
# AC-TEST-003: copyfile replacement overwrites existing file atomically
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_copyfile_replaces_existing_file_with_new_content(tmp_path: pathlib.Path) -> None:
    """_Copy() overwrites an existing destination file with the current source content.

    AC-TEST-003: when the destination already exists with stale content,
    _Copy() must remove it and write fresh content from the source. The
    operation must succeed without error.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "version.txt"
    src_file.write_text("v2.0.0\n", encoding="utf-8")

    dest = topdir / "version.txt"
    dest.write_text("v1.0.0\n", encoding="utf-8")
    assert dest.read_text(encoding="utf-8") == "v1.0.0\n", "Pre-condition: stale file must exist."

    cf = _make_copyfile(worktree, "version.txt", topdir, "version.txt")
    cf._Copy()

    assert dest.is_file(), f"Expected {dest} to be a regular file after replacement."
    assert not os.path.islink(str(dest)), f"Expected {dest} to be a regular file, not a symlink."
    updated_content = dest.read_text(encoding="utf-8")
    assert updated_content == "v2.0.0\n", (
        f"Expected dest to contain 'v2.0.0' after overwrite, but got: {updated_content!r}"
    )


@pytest.mark.integration
def test_copyfile_replaces_read_only_existing_file(tmp_path: pathlib.Path) -> None:
    """_Copy() removes and replaces a read-only destination file.

    AC-TEST-003: the _Copy() implementation removes the existing file before
    writing (to handle read-only destinations). This test confirms that a
    read-only dest is replaced without raising a PermissionError.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "config.conf"
    src_file.write_text("updated=true\n", encoding="utf-8")

    dest = topdir / "config.conf"
    dest.write_text("old=true\n", encoding="utf-8")
    dest.chmod(0o444)

    assert dest.read_text(encoding="utf-8") == "old=true\n", "Pre-condition: stale read-only file must exist."
    assert stat.S_IMODE(os.stat(str(dest)).st_mode) == 0o444, "Pre-condition: dest must be read-only."

    cf = _make_copyfile(worktree, "config.conf", topdir, "config.conf")
    cf._Copy()

    assert dest.is_file(), f"Expected {dest} to be a regular file after replacing read-only dest."
    assert not os.path.islink(str(dest)), f"Expected {dest} to be a regular file, not a symlink."
    result_content = dest.read_text(encoding="utf-8")
    assert result_content == "updated=true\n", (
        f"Expected dest to contain updated content after replacing read-only file, but got: {result_content!r}"
    )


@pytest.mark.integration
def test_copyfile_idempotent_when_source_unchanged(tmp_path: pathlib.Path) -> None:
    """Calling _Copy() twice with an unchanged source leaves the dest unchanged.

    AC-TEST-003: _Copy() is idempotent -- when source and dest are already
    identical (filecmp.cmp returns True), a second call is a no-op and does
    not modify the destination file.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "settings.json"
    src_file.write_text('{"version": 1}\n', encoding="utf-8")

    cf = _make_copyfile(worktree, "settings.json", topdir, "settings.json")
    cf._Copy()

    dest = topdir / "settings.json"
    assert not os.path.islink(str(dest)), f"Expected {dest} to be a regular file, not a symlink."
    first_mtime = dest.stat().st_mtime

    # Second call with unchanged source -- should skip the copy (filecmp.cmp == True).
    cf._Copy()

    second_mtime = dest.stat().st_mtime
    assert second_mtime == first_mtime, (
        f"Expected idempotent _Copy() to leave mtime unchanged "
        f"({first_mtime}) when source is already identical, but mtime changed to {second_mtime}."
    )
    assert dest.read_text(encoding="utf-8") == '{"version": 1}\n', (
        "Expected dest content to remain correct after second idempotent _Copy() call."
    )


@pytest.mark.integration
def test_copyfile_replacement_produces_independent_file(tmp_path: pathlib.Path) -> None:
    """After replacing an existing dest, the new file is independent of the source.

    AC-TEST-003, AC-FUNC-001: the replacement is a real copy -- modifying the
    source after a replacement _Copy() must not affect the copied destination.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "app.conf"
    src_file.write_text("setting=new\n", encoding="utf-8")

    dest = topdir / "app.conf"
    dest.write_text("setting=old\n", encoding="utf-8")

    cf = _make_copyfile(worktree, "app.conf", topdir, "app.conf")
    cf._Copy()

    copied_content = dest.read_text(encoding="utf-8")
    assert copied_content == "setting=new\n", "Pre-condition: replacement must have happened."
    assert not os.path.islink(str(dest)), f"Expected {dest} to be a regular file, not a symlink."

    # Overwrite the source -- the replacement copy must not be affected.
    src_file.write_text("setting=mutated\n", encoding="utf-8")

    final_content = dest.read_text(encoding="utf-8")
    assert final_content == "setting=new\n", (
        f"Expected the replaced dest to retain copied content after source was mutated, "
        f"but got {final_content!r}. The copy must be independent of the source."
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001: copyfile produces an actual filesystem copy
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_copyfile_produces_filesystem_copy_with_correct_size(tmp_path: pathlib.Path) -> None:
    """_Copy() produces a dest file whose size matches the source exactly.

    AC-FUNC-001: a real filesystem copy must have the same byte count as
    the source. This rules out zero-byte stubs or truncated copies.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    content = "a" * 4096 + "\n"
    src_file = worktree / "large.txt"
    src_file.write_text(content, encoding="utf-8")
    expected_size = src_file.stat().st_size

    cf = _make_copyfile(worktree, "large.txt", topdir, "large.txt")
    cf._Copy()

    dest = topdir / "large.txt"
    assert not os.path.islink(str(dest)), f"Expected {dest} to be a regular file, not a symlink."
    actual_size = dest.stat().st_size
    assert actual_size == expected_size, (
        f"Expected dest size {expected_size} bytes to match source, but got {actual_size} bytes. "
        f"_Copy() must produce a complete filesystem copy."
    )


@pytest.mark.integration
def test_copyfile_produces_copy_in_nested_dest_directory(tmp_path: pathlib.Path) -> None:
    """_Copy() creates intermediate directories and places a regular file copy inside.

    AC-FUNC-001: the dest is a regular file even when placed inside newly
    created nested parent directories.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "values.yaml"
    src_file.write_text("env: staging\n", encoding="utf-8")

    cf = _make_copyfile(worktree, "values.yaml", topdir, "helm/charts/values.yaml")
    cf._Copy()

    dest = topdir / "helm" / "charts" / "values.yaml"
    assert dest.exists(), f"Expected {dest} to exist after _Copy() with nested dest."
    assert not os.path.islink(str(dest)), f"Expected {dest} to be a regular file, not a symlink."
    dest_stat = os.lstat(str(dest))
    assert stat.S_ISREG(dest_stat.st_mode), (
        f"Expected {dest} inode to be a regular file (mode {dest_stat.st_mode:#o}), but S_ISREG returned False."
    )
    assert dest.read_text(encoding="utf-8") == "env: staging\n", "Expected dest content to match source."


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: no stdout leakage
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_copyfile_copy_does_not_write_to_stdout(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
    """_Copy() does not write any output to stdout on a successful invocation.

    AC-CHANNEL-001: library code must not print to stdout. All diagnostic
    output must go through the logging system (stderr) or be suppressed.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "output.txt"
    src_file.write_text("data\n", encoding="utf-8")

    cf = _make_copyfile(worktree, "output.txt", topdir, "output.txt")
    cf._Copy()

    captured = capsys.readouterr()
    assert not captured.out, f"Expected no stdout output from _CopyFile._Copy(), but got: {captured.out!r}"


@pytest.mark.integration
def test_copyfile_replacement_does_not_write_to_stdout(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
    """_Copy() replacing an existing file does not write to stdout.

    AC-CHANNEL-001: the replacement path (remove existing + copy) must also
    produce no stdout output. Only the logging system may emit output.
    """
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "file.txt"
    src_file.write_text("new content\n", encoding="utf-8")

    dest = topdir / "file.txt"
    dest.write_text("old content\n", encoding="utf-8")

    cf = _make_copyfile(worktree, "file.txt", topdir, "file.txt")
    cf._Copy()

    captured = capsys.readouterr()
    assert not captured.out, (
        f"Expected no stdout output from _CopyFile._Copy() during file replacement, but got: {captured.out!r}"
    )
