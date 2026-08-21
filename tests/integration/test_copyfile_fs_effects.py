"""Integration tests for copyfile filesystem effects.

Tests cover actual on-disk behavior produced by _CopyFile._Copy():
- AC-TEST-001: regular file creation (not a symlink)
- AC-TEST-002: source file permissions preserved in the copy
- AC-TEST-003: atomic replacement of an existing destination file
- AC-TEST-004: absolute dest delivers a real file outside topdir

AC-FUNC-001: copyfile produces an actual filesystem copy (bytes on disk).
AC-CHANNEL-001: no stdout leakage on success paths.
"""

import contextlib
import io
import logging
import os
import pathlib
import stat

import pytest

from kanon_cli.repo.error import ManifestInvalidPathError
from kanon_cli.repo import project as project_module
from kanon_cli.repo.project import _CopyFile


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
        dest: Destination path relative to topdir, or absolute (spec 17.1).

    Returns:
        A configured _CopyFile instance.
    """
    return _CopyFile(str(git_worktree), src, str(topdir), dest)


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

    src_file.write_text("completely different content\n", encoding="utf-8")

    dest_content = dest.read_text(encoding="utf-8")
    assert dest_content == original_content, (
        f"Expected dest to retain original content {original_content!r} after source was overwritten, "
        f"but got {dest_content!r}. _Copy() must produce an independent file, not a symlink."
    )


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

    dest.chmod(0o644)
    src_file.chmod(0o644)


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

    src_file.write_text("setting=mutated\n", encoding="utf-8")

    final_content = dest.read_text(encoding="utf-8")
    assert final_content == "setting=new\n", (
        f"Expected the replaced dest to retain copied content after source was mutated, "
        f"but got {final_content!r}. The copy must be independent of the source."
    )


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


@pytest.mark.integration
def test_copyfile_absolute_dest_creates_regular_file_outside_topdir(tmp_path: pathlib.Path, permit_abs_roots) -> None:
    """_Copy() with an absolute dest creates a real file at that absolute path.

    AC-TEST-004: the absolute dest branch allows the copy to be placed outside
    the workspace topdir. The resulting entry must be a regular file (not a
    symlink) whose content matches the source.
    """
    permit_abs_roots(tmp_path)
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "schema.json"
    src_file.write_text('{"schema": true}\n', encoding="utf-8")

    abs_dest = str(tmp_path / "absolute-copy" / "schema.json")

    cf = _make_copyfile(worktree, "schema.json", topdir, abs_dest)
    cf._Copy()

    assert os.path.isfile(abs_dest), f"Expected a regular file at the absolute dest path {abs_dest!r} after _Copy()."
    assert not os.path.islink(abs_dest), f"Expected {abs_dest!r} to be a real file, not a symlink."
    resolved = pathlib.Path(abs_dest).read_text(encoding="utf-8")
    assert resolved == '{"schema": true}\n', (
        f"Expected file at absolute dest {abs_dest!r} to contain source content, but read: {resolved!r}"
    )


@pytest.mark.integration
def test_copyfile_absolute_dest_is_actual_file_not_symlink(tmp_path: pathlib.Path, permit_abs_roots) -> None:
    """The entry at an absolute dest path is a regular file, not a symlink.

    AC-TEST-004: confirms that the branch handling absolute dest paths still
    copies bytes (via shutil.copy) rather than creating a symlink, unlike
    linkfile's equivalent absolute-dest handling.
    """
    permit_abs_roots(tmp_path)
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "README.md"
    src_file.write_text("# project\n", encoding="utf-8")

    abs_dest = str(tmp_path / "out" / "README.md")

    cf = _make_copyfile(worktree, "README.md", topdir, abs_dest)
    cf._Copy()

    dest_stat = os.lstat(abs_dest)
    assert stat.S_ISREG(dest_stat.st_mode), (
        f"Expected lstat at {abs_dest!r} to show a regular file (mode {dest_stat.st_mode:#o}), "
        f"but S_ISREG returned False."
    )
    assert not stat.S_ISLNK(dest_stat.st_mode), (
        f"Expected {abs_dest!r} not to be a symbolic link (mode {dest_stat.st_mode:#o}), but S_ISLNK returned True."
    )


@pytest.mark.integration
def test_copyfile_absolute_dest_creates_parent_dirs(tmp_path: pathlib.Path, permit_abs_roots) -> None:
    """_Copy() with an absolute dest creates intermediate parent directories.

    AC-TEST-004: nested absolute destinations must have their parent
    directories created automatically, matching linkfile's behavior.
    """
    permit_abs_roots(tmp_path)
    worktree = tmp_path / "project"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()

    src_file = worktree / "tool.conf"
    src_file.write_text("setting=true\n", encoding="utf-8")

    abs_dest = str(tmp_path / "deep" / "nested" / "dir" / "tool.conf")

    cf = _make_copyfile(worktree, "tool.conf", topdir, abs_dest)
    cf._Copy()

    assert os.path.isfile(abs_dest), (
        f"Expected a regular file at {abs_dest!r} after _Copy() with nested absolute dest, "
        f"but the path does not exist or is not a file."
    )


@pytest.mark.integration
def test_copyfile_absolute_dest_outside_permitted_roots_is_rejected(tmp_path: pathlib.Path, permit_abs_roots) -> None:
    """An absolute dest outside every permitted root raises and writes nothing.

    A manifest is fetched from a remote repository, so an unconfined absolute dest
    is an arbitrary-file-write primitive. Only paths under a permitted root may be
    written; everything else is refused before any filesystem effect occurs.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()
    permit_abs_roots(project_root)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()
    (worktree / "payload.txt").write_text("payload\n", encoding="utf-8")

    outside = tmp_path / "outside" / "authorized_keys"

    cf = _make_copyfile(worktree, "payload.txt", topdir, str(outside))
    with pytest.raises(ManifestInvalidPathError, match="outside every permitted root"):
        cf._Copy()

    assert not outside.exists(), (
        f"Expected no filesystem effect at {str(outside)!r} for a dest outside the permitted "
        f"roots, but the file was created."
    )


@pytest.mark.integration
def test_copyfile_absolute_dest_error_names_the_dest_and_how_to_widen(tmp_path: pathlib.Path, permit_abs_roots) -> None:
    """The refusal is actionable without a prompt: dest, roots, and the remedy.

    kanon must stay usable non-interactively, so a refused destination cannot fall
    back to asking. The message therefore has to carry everything an operator needs.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()
    permit_abs_roots(project_root)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()
    (worktree / "payload.txt").write_text("payload\n", encoding="utf-8")

    outside = str(tmp_path / "elsewhere" / "file.txt")
    cf = _make_copyfile(worktree, "payload.txt", topdir, outside)

    with pytest.raises(ManifestInvalidPathError) as excinfo:
        cf._Copy()

    message = str(excinfo.value)
    assert outside in message, f"Expected the refusal to name the offending dest, got {message!r}."
    assert str(project_root) in message, f"Expected the refusal to list the permitted roots, got {message!r}."
    assert "--allow-abs-root" in message and "KANON_ALLOWED_ABS_ROOTS" in message, (
        f"Expected the refusal to name both ways to widen the boundary, got {message!r}."
    )


@pytest.mark.integration
def test_copyfile_absolute_dest_through_intermediate_symlink_is_rejected(
    tmp_path: pathlib.Path, permit_abs_roots
) -> None:
    """A symlinked path component cannot be used to escape the permitted root.

    The checked-out tree is attacker-controlled, so a manifest can ship a symlink
    and a copyfile that traverses it. Containment on the literal path alone would
    not stop that, which is why every component is walked.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()
    permit_abs_roots(project_root)

    secret_dir = tmp_path / "outside-target"
    secret_dir.mkdir()
    (project_root / "innocent").symlink_to(secret_dir)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()
    (worktree / "hook").write_text("payload\n", encoding="utf-8")

    through_link = str(project_root / "innocent" / "pre-commit")

    cf = _make_copyfile(worktree, "hook", topdir, through_link)
    with pytest.raises(ManifestInvalidPathError, match="outside every permitted root"):
        cf._Copy()

    assert not (secret_dir / "pre-commit").exists(), (
        "Expected no write through the symlinked component, but the target was created."
    )


@pytest.mark.integration
def test_copyfile_absolute_dest_dangling_symlink_does_not_write_through(
    tmp_path: pathlib.Path, permit_abs_roots
) -> None:
    """A dangling symlink at dest must not become a write to its target.

    ``os.path.exists`` follows symlinks and is False for a dangling one, so an
    unguarded copy would open through the link and create the target instead of
    replacing the link.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()
    permit_abs_roots(project_root)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()
    (worktree / "payload.txt").write_text("payload\n", encoding="utf-8")

    target = tmp_path / "outside-target" / "victim.txt"
    dest_link = project_root / "dangling.txt"
    dest_link.symlink_to(target)

    cf = _make_copyfile(worktree, "payload.txt", topdir, str(dest_link))
    with pytest.raises(ManifestInvalidPathError, match="traversing symlinks"):
        cf._Copy()

    assert not target.exists(), (
        f"Expected no write through the dangling symlink to {str(target)!r}, but it was created."
    )


@pytest.mark.integration
def test_copyfile_absolute_dest_permission_denied_raises(tmp_path: pathlib.Path, permit_abs_roots) -> None:
    """An unwritable destination fails loudly rather than reporting success.

    A swallowed copy failure let the sync report success having delivered nothing,
    which is the silent-failure mode kanon forbids. Permission failure is the common
    case once a destination can sit outside the workspace.
    """
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory permissions, so the denial cannot be provoked")

    project_root = tmp_path / "project"
    project_root.mkdir()
    permit_abs_roots(project_root)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()
    (worktree / "payload.txt").write_text("payload\n", encoding="utf-8")

    locked = project_root / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        cf = _make_copyfile(worktree, "payload.txt", topdir, str(locked / "out.txt"))
        with pytest.raises(OSError, match="Cannot copy file"):
            cf._Copy()
    finally:
        locked.chmod(0o755)


@pytest.mark.integration
def test_copyfile_absolute_dest_special_file_is_rejected(tmp_path: pathlib.Path, permit_abs_roots) -> None:
    """A fifo on the destination path is refused, matching the relative-dest rule.

    ``_SafeExpandPath`` refuses a non-regular file on a relative dest; an absolute
    dest must not be the weaker of the two.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()
    permit_abs_roots(project_root)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()
    (worktree / "payload.txt").write_text("payload\n", encoding="utf-8")

    fifo_dir = project_root / "pipe"
    os.mkfifo(str(fifo_dir))

    cf = _make_copyfile(worktree, "payload.txt", topdir, str(fifo_dir / "out.txt"))
    with pytest.raises(ManifestInvalidPathError, match="only regular files"):
        cf._Copy()


@pytest.mark.integration
def test_copyfile_absolute_dest_fails_closed_when_no_root_configured(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no permitted root published, every absolute dest is refused.

    Driving the vendored tool without kanon leaves the boundary unset. Defaulting
    to "anything goes" there would reopen the hole, so the unset case refuses.
    """
    monkeypatch.delenv("KANON_PERMITTED_ABS_ROOTS", raising=False)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()
    (worktree / "payload.txt").write_text("payload\n", encoding="utf-8")

    dest = tmp_path / "anywhere.txt"
    cf = _make_copyfile(worktree, "payload.txt", topdir, str(dest))

    with pytest.raises(ManifestInvalidPathError, match="no permitted root is configured"):
        cf._Copy()

    assert not dest.exists(), "Expected no filesystem effect when the boundary is unconfigured."


@pytest.mark.integration
def test_copyfile_absolute_dest_symlink_inside_permitted_root_is_still_rejected(
    tmp_path: pathlib.Path, permit_abs_roots
) -> None:
    """A symlinked component is refused even when it stays inside the boundary.

    Containment alone cannot catch this: the link resolves to a permitted location,
    so only the component walk refuses it. Without that walk a manifest could still
    redirect a write within the project -- into ``.git/hooks``, for instance.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()
    permit_abs_roots(project_root)

    real_dir = project_root / "real"
    real_dir.mkdir()
    (project_root / "alias").symlink_to(real_dir)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()
    (worktree / "payload.txt").write_text("payload\n", encoding="utf-8")

    cf = _make_copyfile(worktree, "payload.txt", topdir, str(project_root / "alias" / "out.txt"))
    with pytest.raises(ManifestInvalidPathError, match="traversing symlinks"):
        cf._Copy()

    assert not (real_dir / "out.txt").exists(), (
        "Expected no write through a symlinked component even inside the permitted root."
    )


@contextlib.contextmanager
def _captured_repo_warnings():
    """Capture what the vendored tree's logger emits.

    ``RepoLogger`` is constructed directly rather than through
    ``logging.getLogger``, so it sits outside the logging hierarchy and its
    ``StreamHandler`` holds the ``sys.stderr`` object from import time. Neither
    ``capsys`` nor ``caplog`` sees it. Attaching a handler to the logger itself
    tests the message the code actually emits, without depending on how pytest
    happens to be capturing.

    Yields:
        A buffer holding everything the logger emitted inside the block.
    """
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(logging.Formatter("%(message)s"))
    project_module.logger.addHandler(handler)
    try:
        yield buffer
    finally:
        project_module.logger.removeHandler(handler)


@pytest.mark.integration
def test_copyfile_absolute_dest_overwrite_warns(tmp_path: pathlib.Path, permit_abs_roots) -> None:
    """Destroying an existing file at an absolute dest must not be silent.

    An absolute dest resolves into the consumer's own project, so a file already
    there may be theirs rather than repo-managed. A copy is irreversible where a
    symlink replacement is not, yet `_LinkFile` warned and `_CopyFile` did not --
    the destructive operation was the quiet one.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()
    permit_abs_roots(project_root)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()
    (worktree / "payload.txt").write_text("from the manifest\n", encoding="utf-8")

    dest = project_root / "existing.txt"
    dest.write_text("the operator's own content\n", encoding="utf-8")

    cf = _make_copyfile(worktree, "payload.txt", topdir, str(dest))
    with _captured_repo_warnings() as emitted:
        cf._Copy()

    warning = emitted.getvalue()
    assert dest.read_text(encoding="utf-8") == "from the manifest\n"
    assert "Overwriting existing file" in warning, (
        f"expected a warning before destroying the operator's file; got {warning!r}"
    )
    assert str(dest) in warning, "the warning must name the file that was destroyed"


@pytest.mark.integration
def test_copyfile_relative_dest_overwrite_is_quiet(tmp_path: pathlib.Path) -> None:
    """A relative dest is repo-managed, so replacing it is routine, not notable.

    Warning there would make every ordinary sync noisy and train operators to
    ignore the warning that matters.
    """
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    topdir = tmp_path / "workspace"
    topdir.mkdir()
    (worktree / "payload.txt").write_text("from the manifest\n", encoding="utf-8")
    (topdir / "managed.txt").write_text("previous sync\n", encoding="utf-8")

    cf = _make_copyfile(worktree, "payload.txt", topdir, "managed.txt")
    with _captured_repo_warnings() as emitted:
        cf._Copy()

    assert "Overwriting existing file" not in emitted.getvalue()
