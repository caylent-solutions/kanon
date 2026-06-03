"""Tests for clean core business logic."""

import datetime
import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import (
    clean,
    remove_kanon_dir,
    remove_marketplace_dir,
    remove_packages_dir,
)
from kanon_cli.core.lockfile import (
    CatalogBlock,
    Lockfile,
    SourceEntry,
    write_lockfile,
)

_MINIMAL_KANONENV = (
    "KANON_SOURCE_build_URL=https://example.com\nKANON_SOURCE_build_REVISION=main\nKANON_SOURCE_build_PATH=meta.xml\n"
)


@pytest.mark.unit
class TestDirectoryRemoval:
    def test_removes_marketplace(self, tmp_path: pathlib.Path) -> None:
        mp = tmp_path / "mp"
        mp.mkdir()
        (mp / "file.txt").write_text("content")
        remove_marketplace_dir(mp)
        assert not mp.exists()

    def test_marketplace_missing_ok(self, tmp_path: pathlib.Path) -> None:
        remove_marketplace_dir(tmp_path / "nonexistent")

    def test_removes_packages(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".packages").mkdir()
        remove_packages_dir(tmp_path)
        assert not (tmp_path / ".packages").exists()

    def test_packages_missing_ok(self, tmp_path: pathlib.Path) -> None:
        remove_packages_dir(tmp_path)

    def test_removes_kanon(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".kanon-data").mkdir()
        remove_kanon_dir(tmp_path)
        assert not (tmp_path / ".kanon-data").exists()

    def test_kanon_missing_ok(self, tmp_path: pathlib.Path) -> None:
        remove_kanon_dir(tmp_path)


@pytest.mark.unit
class TestCleanLifecycle:
    def test_marketplace_false_skips_uninstall(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("KANON_MARKETPLACE_INSTALL=false\n" + _MINIMAL_KANONENV)
        (tmp_path / ".packages").mkdir()
        (tmp_path / ".kanon-data").mkdir(exist_ok=True)
        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins") as mock_uninstall:
            clean(kanonenv)
            mock_uninstall.assert_not_called()
        assert not (tmp_path / ".packages").exists()

    def test_marketplace_true_missing_dir_exits(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("KANON_MARKETPLACE_INSTALL=true\n" + _MINIMAL_KANONENV)
        with pytest.raises(SystemExit):
            clean(kanonenv)

    def test_order_of_operations(self, tmp_path: pathlib.Path) -> None:
        mp_dir = tmp_path / ".mp"
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(f"CLAUDE_MARKETPLACES_DIR={mp_dir}\nKANON_MARKETPLACE_INSTALL=true\n" + _MINIMAL_KANONENV)
        mp_dir.mkdir()
        (tmp_path / ".packages").mkdir()
        (tmp_path / ".kanon-data").mkdir(exist_ok=True)

        ops: list[str] = []

        def track_uninstall(marketplace_dir):
            ops.append("uninstall")

        orig_rmtree = __import__("shutil").rmtree

        def track_rm(path, ignore_errors=False):
            p = str(path)
            if ".mp" in p:
                ops.append("rm_mp")
            elif ".packages" in p:
                ops.append("rm_packages")
            elif ".kanon-data" in p:
                ops.append("rm_kanon")
            orig_rmtree(path, ignore_errors=ignore_errors)

        with (
            patch("kanon_cli.core.clean.uninstall_marketplace_plugins", side_effect=track_uninstall),
            patch("kanon_cli.core.clean.shutil.rmtree", side_effect=track_rm),
        ):
            clean(kanonenv)

        assert ops == ["uninstall", "rm_mp", "rm_packages", "rm_kanon"]


@pytest.mark.unit
class TestCleanSymlinkResolution:
    """Verify AC-1 and AC-2: clean() resolves .kanon symlinks before using kanonenv_path.parent.

    When .kanon is a symlink pointing into a subdirectory, .packages/ and .kanon-data/
    must be removed from the symlink target's parent (the real project directory), not
    from the symlink's parent.
    """

    def test_clean_removes_dirs_from_symlink_target_parent(self, tmp_path: pathlib.Path) -> None:
        """AC-1/AC-2: clean() uses the resolved path so artifacts are removed from the real project.

        Layout:
          tmp_path/
            real_project/
              .kanon           <- the real .kanon file
              .packages/       <- must be removed by clean()
              .kanon-data/     <- must be removed by clean()
            symlink_dir/
              .kanon -> ../real_project/.kanon   <- symlink passed to clean()
              .packages/       <- must NOT be touched by clean()
        """
        real_project = tmp_path / "real_project"
        real_project.mkdir()
        symlink_dir = tmp_path / "symlink_dir"
        symlink_dir.mkdir()

        # Create the real .kanon file in real_project
        real_kanonenv = real_project / ".kanon"
        real_kanonenv.write_text("KANON_MARKETPLACE_INSTALL=false\n" + _MINIMAL_KANONENV)

        # Create the symlink in symlink_dir pointing to the real .kanon
        symlink_kanonenv = symlink_dir / ".kanon"
        symlink_kanonenv.symlink_to(real_kanonenv)

        # Set up artifact directories in both locations
        (real_project / ".packages").mkdir()
        (real_project / ".kanon-data").mkdir()
        (symlink_dir / ".packages").mkdir()  # should NOT be touched

        # Preconditions: verify symlink is set up correctly
        assert symlink_kanonenv.is_symlink(), "AC-2 setup: .kanon in symlink_dir must be a symlink"
        assert symlink_kanonenv.resolve() == real_kanonenv, "AC-2 setup: symlink must point to real .kanon"
        assert (real_project / ".packages").exists(), "AC-2 setup: real_project/.packages must exist before clean()"
        assert (symlink_dir / ".packages").exists(), "AC-2 setup: symlink_dir/.packages must exist before clean()"

        clean(symlink_kanonenv)

        assert not (real_project / ".packages").exists(), (
            "AC-1/AC-2: .packages/ must be removed from symlink target's parent (real_project)"
        )
        assert not (real_project / ".kanon-data").exists(), (
            "AC-1/AC-2: .kanon-data/ must be removed from symlink target's parent (real_project)"
        )
        assert (symlink_dir / ".packages").exists(), (
            "AC-1/AC-2: .packages/ in the symlink's parent (symlink_dir) must NOT be removed"
        )


# ---------------------------------------------------------------------------
# Tests for add_help=True on the 'clean' subparser
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanSubparserHelp:
    """The 'clean' subparser has add_help=True and accepts '-h'."""

    def test_clean_short_dash_h_exits_0(self) -> None:
        """kanon clean -h exits 0 (add_help=True on the clean subparser)."""

        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["clean", "-h"])
        assert exc_info.value.code == 0

    def test_clean_subparser_has_add_help_true(self) -> None:
        """The 'clean' subparser has add_help=True set explicitly."""
        import argparse

        from kanon_cli.commands.clean import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        clean_parser = subparsers.choices["clean"]
        assert clean_parser.add_help is True, "clean subparser must have add_help=True so '-h' is accepted"


# ---------------------------------------------------------------------------
# AC-2: clean honors KANON_WORKSPACE_DIR
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanWorkspaceDirEnvVar:
    """clean() removes .packages/ and .kanon-data/ from KANON_WORKSPACE_DIR when set."""

    def test_clean_removes_dirs_from_workspace_dir(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-2: clean removes .packages/ and .kanon-data/ from KANON_WORKSPACE_DIR."""
        alt_workspace = tmp_path / "alt_workspace"
        cwd_dir = tmp_path / "project"
        cwd_dir.mkdir()

        kanonenv = cwd_dir / ".kanon"
        kanonenv.write_text("KANON_MARKETPLACE_INSTALL=false\n" + _MINIMAL_KANONENV)

        # Create artifacts under the alt workspace (as install would have)
        (alt_workspace / ".packages").mkdir(parents=True)
        (alt_workspace / ".kanon-data").mkdir(parents=True)
        # Also create decoy artifacts in cwd (should NOT be touched by clean)
        (cwd_dir / ".packages").mkdir()
        (cwd_dir / ".kanon-data").mkdir()

        monkeypatch.setenv("KANON_WORKSPACE_DIR", str(alt_workspace))

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not (alt_workspace / ".packages").exists(), (
            "KANON_WORKSPACE_DIR set: .packages/ must be removed from the alt workspace"
        )
        assert not (alt_workspace / ".kanon-data").exists(), (
            "KANON_WORKSPACE_DIR set: .kanon-data/ must be removed from the alt workspace"
        )
        # Decoy artifacts in cwd must not be touched
        assert (cwd_dir / ".packages").exists(), (
            "KANON_WORKSPACE_DIR set: .packages/ in cwd must NOT be touched by clean"
        )
        assert (cwd_dir / ".kanon-data").exists(), (
            "KANON_WORKSPACE_DIR set: .kanon-data/ in cwd must NOT be touched by clean"
        )

    def test_clean_without_workspace_dir_uses_kanonenv_parent(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When KANON_WORKSPACE_DIR is not set, clean removes dirs beside .kanon (original behavior)."""
        cwd_dir = tmp_path / "project"
        cwd_dir.mkdir()
        monkeypatch.delenv("KANON_WORKSPACE_DIR", raising=False)

        kanonenv = cwd_dir / ".kanon"
        kanonenv.write_text("KANON_MARKETPLACE_INSTALL=false\n" + _MINIMAL_KANONENV)

        (cwd_dir / ".packages").mkdir()
        (cwd_dir / ".kanon-data").mkdir()

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not (cwd_dir / ".packages").exists(), (
            "Without KANON_WORKSPACE_DIR, .packages/ must be removed beside .kanon"
        )
        assert not (cwd_dir / ".kanon-data").exists(), (
            "Without KANON_WORKSPACE_DIR, .kanon-data/ must be removed beside .kanon"
        )


# ---------------------------------------------------------------------------
# clean(orphans=...) ledger-driven marketplace pruning
# ---------------------------------------------------------------------------


def _make_source(name: str, *, registered_marketplaces: list[str]) -> SourceEntry:
    """Build a valid SourceEntry carrying a per-source marketplace ledger."""
    return SourceEntry(
        name=name,
        url=f"https://example.com/{name}.git",
        revision_spec="main",
        resolved_ref="refs/heads/main",
        resolved_sha="a" * 40,
        path=f"repo-specs/{name}.xml",
        registered_marketplaces=registered_marketplaces,
    )


def _write_v3_lock(
    base_dir: pathlib.Path,
    *,
    marketplace_dir: pathlib.Path,
    sources: list[SourceEntry],
) -> pathlib.Path:
    """Write a real schema-v3 .kanon.lock with per-source marketplace ledgers.

    The catalog block and hash are synthetic-but-valid so read_lockfile parses
    the file without raising. Returns the lockfile path.
    """
    lockfile = Lockfile(
        schema_version=3,
        generated_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        generator="kanon-cli/test",
        kanon_hash="sha256:" + ("a" * 64),
        catalog=CatalogBlock(
            source="https://catalog.example.com/repo.git@main",
            url="https://catalog.example.com/repo.git",
            revision_spec="main",
            resolved_ref="refs/heads/main",
            resolved_sha="b" * 40,
        ),
        sources=sources,
        marketplace_registered=True,
        marketplace_dir=str(marketplace_dir),
    )
    lock_path = base_dir / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return lock_path


def _write_kanon_sources(
    directory: pathlib.Path, marketplace_dir: pathlib.Path, source_names: list[str]
) -> pathlib.Path:
    """Write a .kanon declaring the given source names (marketplace install on)."""
    lines = [
        f"CLAUDE_MARKETPLACES_DIR={marketplace_dir}",
        "KANON_MARKETPLACE_INSTALL=true",
    ]
    for name in source_names:
        lines.append(f"KANON_SOURCE_{name}_URL=https://example.com/{name}.git")
        lines.append(f"KANON_SOURCE_{name}_REVISION=main")
        lines.append(f"KANON_SOURCE_{name}_PATH=repo-specs/{name}.xml")
    kanonenv = directory / ".kanon"
    kanonenv.write_text("\n".join(lines) + "\n")
    return kanonenv


_KEEP_SET_NAMES = ("claude-plugins-official", "devbench-authoring")


@pytest.mark.unit
class TestCleanOrphansSourcePrune:
    """``clean(orphans=True)`` unregisters marketplaces of sources removed from .kanon.

    SAFETY INVARIANT: removal candidates come ONLY from the per-source
    ``registered_marketplaces`` ledgers of sources in the lock but absent from
    the current .kanon. A marketplace still provided by a referenced source, and
    user/keep-set names never written to any ledger, must never be passed to
    ``remove_marketplace``.
    """

    def test_orphaned_source_marketplace_is_pruned_keepset_and_referenced_untouched(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Lock has A+B; .kanon has only B -> prune A's marketplace, keep B's; keep-set untouched.

        Source A (removed from .kanon) registered ``alpha-mp``; source B (still
        in .kanon) registered ``bravo-mp``. Only ``alpha-mp`` must be removed; B's
        marketplace and any keep-set name must never be removed.
        """
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        # .kanon declares only source B; the lock still records A and B.
        kanonenv = _write_kanon_sources(tmp_path, marketplace_dir, ["bravo"])
        (tmp_path / ".packages").mkdir()

        _write_v3_lock(
            tmp_path,
            marketplace_dir=marketplace_dir,
            sources=[
                _make_source("alpha", registered_marketplaces=["alpha-mp"]),
                _make_source("bravo", registered_marketplaces=["bravo-mp"]),
            ],
        )

        removed: list[str] = []

        def _track_remove(claude_bin, name):
            removed.append(name)
            return True

        with (
            patch("kanon_cli.core.clean.locate_claude_binary", return_value="/usr/bin/claude") as mock_locate,
            patch("kanon_cli.core.clean.remove_marketplace", side_effect=_track_remove),
            patch("kanon_cli.core.clean.uninstall_marketplace_plugins"),
        ):
            clean(kanonenv, orphans=True)

        assert removed == ["alpha-mp"], (
            f"Only orphaned source A's marketplace 'alpha-mp' must be removed; got {removed!r}"
        )
        assert "bravo-mp" not in removed, "A still-referenced source's marketplace must not be removed"
        for keep in _KEEP_SET_NAMES:
            assert keep not in removed, (
                f"Keep-set marketplace {keep!r} was never in any ledger and must never be removed; got {removed!r}"
            )
        mock_locate.assert_called_once()

    def test_marketplace_shared_by_referenced_source_is_not_pruned(self, tmp_path: pathlib.Path) -> None:
        """A marketplace registered by BOTH an orphaned and a referenced source is retained.

        Source A (removed) and source B (kept) both registered ``shared-mp``; A
        also registered ``alpha-only-mp``. Only ``alpha-only-mp`` is pruned --
        ``shared-mp`` stays because B still references it.
        """
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        kanonenv = _write_kanon_sources(tmp_path, marketplace_dir, ["bravo"])
        (tmp_path / ".packages").mkdir()

        _write_v3_lock(
            tmp_path,
            marketplace_dir=marketplace_dir,
            sources=[
                _make_source("alpha", registered_marketplaces=["alpha-only-mp", "shared-mp"]),
                _make_source("bravo", registered_marketplaces=["shared-mp"]),
            ],
        )

        removed: list[str] = []

        with (
            patch("kanon_cli.core.clean.locate_claude_binary", return_value="/usr/bin/claude"),
            patch("kanon_cli.core.clean.remove_marketplace", side_effect=lambda claude_bin, name: removed.append(name)),
            patch("kanon_cli.core.clean.uninstall_marketplace_plugins"),
        ):
            clean(kanonenv, orphans=True)

        assert removed == ["alpha-only-mp"], (
            f"Only A's exclusive marketplace must be pruned; 'shared-mp' is still referenced by B; got {removed!r}"
        )

    def test_no_orphaned_sources_does_not_locate_claude_or_remove(self, tmp_path: pathlib.Path) -> None:
        """When every lock source is still in .kanon, no removal and no claude lookup."""
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        kanonenv = _write_kanon_sources(tmp_path, marketplace_dir, ["bravo"])
        (tmp_path / ".packages").mkdir()

        _write_v3_lock(
            tmp_path,
            marketplace_dir=marketplace_dir,
            sources=[_make_source("bravo", registered_marketplaces=["bravo-mp"])],
        )

        with (
            patch("kanon_cli.core.clean.locate_claude_binary") as mock_locate,
            patch("kanon_cli.core.clean.remove_marketplace") as mock_remove,
            patch("kanon_cli.core.clean.uninstall_marketplace_plugins"),
        ):
            clean(kanonenv, orphans=True)

        mock_remove.assert_not_called()
        mock_locate.assert_not_called()

    def test_orphans_false_never_calls_remove_marketplace(self, tmp_path: pathlib.Path) -> None:
        """Regression: the default (orphans=False) path never touches remove_marketplace.

        Even with an orphaned source in the lock, the plain clean path must not
        unregister anything -- the prune is opt-in via --orphans.
        """
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        kanonenv = _write_kanon_sources(tmp_path, marketplace_dir, ["bravo"])
        (tmp_path / ".packages").mkdir()

        _write_v3_lock(
            tmp_path,
            marketplace_dir=marketplace_dir,
            sources=[
                _make_source("alpha", registered_marketplaces=["alpha-mp"]),
                _make_source("bravo", registered_marketplaces=["bravo-mp"]),
            ],
        )

        with (
            patch("kanon_cli.core.clean.remove_marketplace") as mock_remove,
            patch("kanon_cli.core.clean.locate_claude_binary") as mock_locate,
            patch("kanon_cli.core.clean.uninstall_marketplace_plugins"),
        ):
            clean(kanonenv, orphans=False)

        mock_remove.assert_not_called()
        mock_locate.assert_not_called()

    def test_orphaned_source_with_empty_ledger_skips_prune(self, tmp_path: pathlib.Path) -> None:
        """An orphaned source that registered no marketplaces yields nothing to prune."""
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()

        kanonenv = _write_kanon_sources(tmp_path, marketplace_dir, ["bravo"])
        (tmp_path / ".packages").mkdir()

        _write_v3_lock(
            tmp_path,
            marketplace_dir=marketplace_dir,
            sources=[
                _make_source("alpha", registered_marketplaces=[]),
                _make_source("bravo", registered_marketplaces=["bravo-mp"]),
            ],
        )

        with (
            patch("kanon_cli.core.clean.remove_marketplace") as mock_remove,
            patch("kanon_cli.core.clean.locate_claude_binary") as mock_locate,
            patch("kanon_cli.core.clean.uninstall_marketplace_plugins"),
        ):
            clean(kanonenv, orphans=True)

        mock_remove.assert_not_called()
        mock_locate.assert_not_called()
