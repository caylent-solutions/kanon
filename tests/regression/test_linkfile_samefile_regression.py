"""Regression guard: file-level <linkfile> must survive a real ``repo sync``.

Bug: ``kanon install`` exited 1 with ``shutil.SameFileError`` whenever a
marketplace source's manifest declared a ``<linkfile>`` whose ``src`` is a
regular file.

``repo sync`` materializes every ``<linkfile>`` as a symlink at ``dest``
targeting ``src`` (``kanon_cli.repo.project._LinkFile._Link``).  The
post-sync helper ``_process_manifest_linkfiles`` then ran
``shutil.copy2(src, dest)`` on that same pair, and ``shutil.copyfile``
raises ``SameFileError`` when ``src`` and ``dest`` stat to the same inode.
Directory-level linkfiles escaped because the helper's ``src_abs.is_file()``
guard skipped them.

Fix: the helper skips a linkfile whose ``dest`` already resolves to ``src``
-- the state it exists to establish already holds.  Every other failure
still propagates.
"""

import pathlib

import pytest

from kanon_cli.core.install import _process_manifest_linkfiles

MANIFEST_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <project name="pkg" path=".packages/pkg">
    <linkfile src="{src}" dest="{dest}" />
  </project>
</manifest>
"""


def _seed(tmp_path: pathlib.Path, src_rel: str, dest_str: str) -> pathlib.Path:
    """Write a source workspace with one project and one linkfile manifest.

    Args:
        tmp_path: Test-scoped temporary directory used as the source workspace.
        src_rel: ``linkfile`` ``src`` value, relative to the project checkout.
        dest_str: ``linkfile`` ``dest`` value as written in the manifest.

    Returns:
        Absolute path to the manifest XML.
    """
    project_dir = tmp_path / ".packages" / "pkg"
    (project_dir / pathlib.PurePath(src_rel).parent).mkdir(parents=True, exist_ok=True)
    (project_dir / src_rel).write_text("payload\n")

    manifest = tmp_path / "manifest.xml"
    manifest.write_text(MANIFEST_TMPL.format(src=src_rel, dest=dest_str))
    return manifest


class TestFileLinkfileAfterRealRepoSync:
    """``dest`` already symlinked to ``src`` by ``repo sync`` must not crash."""

    @pytest.mark.parametrize(
        "dest_is_absolute",
        [True, False],
        ids=["absolute-dest", "relative-dest"],
    )
    def test_symlinked_dest_is_left_alone(
        self,
        tmp_path: pathlib.Path,
        dest_is_absolute: bool,
    ) -> None:
        """Given: repo sync already symlinked dest -> src for a file linkfile.

        When: ``_process_manifest_linkfiles`` runs over the same manifest.
        Then: it returns without raising and leaves the symlink intact.

        The fixture below mirrors what ``repo sync`` leaves on disk: a
        relative symlink at ``dest`` resolving to ``src``.
        """
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        dest_abs = consumer / ".gitleaks.toml"
        dest_str = str(dest_abs) if dest_is_absolute else "consumer/.gitleaks.toml"

        manifest = _seed(tmp_path, "gitleaks.toml", dest_str)
        src_abs = tmp_path / ".packages" / "pkg" / "gitleaks.toml"

        dest_abs.symlink_to(
            pathlib.Path("..") / src_abs.relative_to(tmp_path),
        )
        assert dest_abs.samefile(src_abs)

        _process_manifest_linkfiles(manifest, tmp_path)

        assert dest_abs.is_symlink(), "repo-managed symlink must survive"
        assert dest_abs.samefile(src_abs)
        assert dest_abs.read_text() == "payload\n"

    def test_absent_dest_is_still_populated(self, tmp_path: pathlib.Path) -> None:
        """Given: repo sync did not run, so dest does not exist.

        When: ``_process_manifest_linkfiles`` runs.
        Then: it copies src to dest, preserving the helper's original purpose.
        """
        dest_abs = tmp_path / "out" / "gitleaks.toml"
        manifest = _seed(tmp_path, "gitleaks.toml", str(dest_abs))

        _process_manifest_linkfiles(manifest, tmp_path)

        assert dest_abs.is_file()
        assert not dest_abs.is_symlink()
        assert dest_abs.read_text() == "payload\n"

    def test_stale_dest_is_overwritten(self, tmp_path: pathlib.Path) -> None:
        """Given: dest exists as an unrelated regular file.

        When: ``_process_manifest_linkfiles`` runs.
        Then: the guard does not fire and src overwrites the stale content.
        """
        dest_abs = tmp_path / "out" / "gitleaks.toml"
        dest_abs.parent.mkdir(parents=True)
        dest_abs.write_text("stale\n")

        manifest = _seed(tmp_path, "gitleaks.toml", str(dest_abs))
        _process_manifest_linkfiles(manifest, tmp_path)

        assert dest_abs.read_text() == "payload\n"

    def test_unwritable_dest_still_fails_fast(self, tmp_path: pathlib.Path) -> None:
        """Given: dest's parent path is occupied by a regular file.

        When: ``_process_manifest_linkfiles`` runs.
        Then: the OSError propagates -- the guard must not swallow real errors.
        """
        blocker = tmp_path / "out"
        blocker.write_text("not a directory\n")
        dest_abs = blocker / "gitleaks.toml"

        manifest = _seed(tmp_path, "gitleaks.toml", str(dest_abs))

        with pytest.raises(OSError):
            _process_manifest_linkfiles(manifest, tmp_path)
