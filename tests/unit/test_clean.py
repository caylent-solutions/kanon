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
    CURRENT_SCHEMA_VERSION,
    Lockfile,
    SourceEntry,
    write_lockfile,
)

_MINIMAL_KANONENV = (
    "KANON_SOURCE_build_URL=https://example.com\n"
    "KANON_SOURCE_build_REF=main\n"
    "KANON_SOURCE_build_PATH=meta.xml\n"
    "KANON_SOURCE_build_NAME=build\n"
    "KANON_SOURCE_build_GITBASE=https://example.com\n"
)

# Same minimal block, but with the 'build' dependency opting into marketplace
# install via the per-dependency flag (spec Section 5.1 / FR-17). Used by the
# clean tests that exercise the marketplace teardown path.
_MINIMAL_KANONENV_MARKETPLACE = _MINIMAL_KANONENV + "KANON_SOURCE_build_MARKETPLACE=true\n"


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

    def test_removes_store_entries(self, tmp_path: pathlib.Path) -> None:
        """remove_store_entries prunes content-addressed entries, keeping the store base."""
        from kanon_cli.core.clean import remove_store_entries
        from kanon_cli.core.install import store_entries_dir

        store = tmp_path / "store"
        (store_entries_dir(store) / "deadbeef").mkdir(parents=True)
        remove_store_entries(store)
        assert not store_entries_dir(store).exists()
        assert store.exists(), "the store base directory must survive a prune"

    def test_store_entries_missing_ok(self, tmp_path: pathlib.Path) -> None:
        """remove_store_entries on an empty store is a no-op (clean before install)."""
        from kanon_cli.core.clean import remove_store_entries

        store = tmp_path / "store"
        store.mkdir()
        remove_store_entries(store)
        assert store.exists()


@pytest.mark.unit
class TestCleanLifecycle:
    def test_marketplace_false_skips_uninstall(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = tmp_path / "home" / "store"
        monkeypatch.setenv("KANON_HOME", str(tmp_path / "home"))
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_MINIMAL_KANONENV)
        (store / ".packages").mkdir(parents=True)
        (store / ".kanon-data").mkdir(parents=True, exist_ok=True)
        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins") as mock_uninstall:
            clean(kanonenv)
            mock_uninstall.assert_not_called()
        assert not (store / ".packages").exists()

    def test_marketplace_true_missing_dir_exits(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_MINIMAL_KANONENV_MARKETPLACE)
        with pytest.raises(SystemExit):
            clean(kanonenv)

    def test_order_of_operations(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mp_dir = tmp_path / ".mp"
        store = tmp_path / "home" / "store"
        monkeypatch.setenv("KANON_HOME", str(tmp_path / "home"))
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(f"CLAUDE_MARKETPLACES_DIR={mp_dir}\n" + _MINIMAL_KANONENV_MARKETPLACE)
        mp_dir.mkdir()
        (store / ".packages").mkdir(parents=True)
        (store / ".kanon-data").mkdir(parents=True, exist_ok=True)

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
    """Verify clean() resolves .kanon symlinks and removes artifacts from the KANON_HOME store.

    Under the shared KANON_HOME store model the fetched artifacts (.packages/,
    .kanon-data/) live under <KANON_HOME>/store, not beside .kanon. clean() must
    still resolve a symlinked .kanon (so the committed .kanon.lock is read from the
    real project directory) and must remove the store artifacts. Directories that
    merely sit beside the .kanon symlink must never be touched.
    """

    def test_clean_resolves_symlink_and_removes_store_artifacts(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """clean() resolves the .kanon symlink and removes .packages/ + .kanon-data/ from the store.

        Layout:
          tmp_path/
            home/store/
              .packages/       <- must be removed by clean()
              .kanon-data/     <- must be removed by clean()
            real_project/
              .kanon           <- the real .kanon file
            symlink_dir/
              .kanon -> ../real_project/.kanon   <- symlink passed to clean()
              .packages/       <- must NOT be touched by clean()
        """
        store = tmp_path / "home" / "store"
        monkeypatch.setenv("KANON_HOME", str(tmp_path / "home"))

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

        # Fetched artifacts live in the shared store; a decoy dir sits beside the symlink.
        (store / ".packages").mkdir(parents=True)
        (store / ".kanon-data").mkdir(parents=True)
        (symlink_dir / ".packages").mkdir()  # should NOT be touched

        # Preconditions: verify symlink is set up correctly
        assert symlink_kanonenv.is_symlink(), "setup: .kanon in symlink_dir must be a symlink"
        assert symlink_kanonenv.resolve() == real_kanonenv, "setup: symlink must point to real .kanon"
        assert (store / ".packages").exists(), "setup: store/.packages must exist before clean()"
        assert (symlink_dir / ".packages").exists(), "setup: symlink_dir/.packages must exist before clean()"

        clean(symlink_kanonenv)

        assert not (store / ".packages").exists(), ".packages/ must be removed from the KANON_HOME store"
        assert not (store / ".kanon-data").exists(), ".kanon-data/ must be removed from the KANON_HOME store"
        assert (symlink_dir / ".packages").exists(), (
            ".packages/ beside the .kanon symlink must NOT be removed by clean()"
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
# AC-23: clean removes artifacts from the shared KANON_HOME store
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanKanonHomeStore:
    """clean() removes .packages/ and .kanon-data/ from the <KANON_HOME>/store."""

    def test_clean_removes_dirs_from_kanon_home_store(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-23: clean removes .packages/ and .kanon-data/ from <KANON_HOME>/store, never from cwd."""
        kanon_home = tmp_path / "home"
        store = kanon_home / "store"
        cwd_dir = tmp_path / "project"
        cwd_dir.mkdir()

        kanonenv = cwd_dir / ".kanon"
        kanonenv.write_text(_MINIMAL_KANONENV)

        # Create artifacts under the store (as install would have)
        (store / ".packages").mkdir(parents=True)
        (store / ".kanon-data").mkdir(parents=True)
        # Also create decoy artifacts in cwd (should NOT be touched by clean)
        (cwd_dir / ".packages").mkdir()
        (cwd_dir / ".kanon-data").mkdir()

        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not (store / ".packages").exists(), ".packages/ must be removed from the KANON_HOME store"
        assert not (store / ".kanon-data").exists(), ".kanon-data/ must be removed from the KANON_HOME store"
        # Decoy artifacts in cwd must not be touched
        assert (cwd_dir / ".packages").exists(), ".packages/ in cwd must NOT be touched by clean"
        assert (cwd_dir / ".kanon-data").exists(), ".kanon-data/ in cwd must NOT be touched by clean"

    def test_clean_default_home_resolves_to_home_kanon_store(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With KANON_HOME unset, clean resolves the store under $HOME/.kanon/store (env-derived).

        The clean removal targets the resolved store; this test points $HOME at a
        temp dir so the default ~/.kanon/store resolves inside the sandbox and no
        real home directory is touched.
        """
        import os

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        store = fake_home / ".kanon" / "store"
        monkeypatch.delenv("KANON_HOME", raising=False)
        # Redirect Path.home() / expanduser by overriding HOME (and USERPROFILE on Windows).
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("USERPROFILE", str(fake_home))
        os.environ.pop("KANON_HOME", None)

        cwd_dir = tmp_path / "project"
        cwd_dir.mkdir()
        kanonenv = cwd_dir / ".kanon"
        kanonenv.write_text(_MINIMAL_KANONENV)

        (store / ".packages").mkdir(parents=True)
        (store / ".kanon-data").mkdir(parents=True)

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not (store / ".packages").exists(), (
            "Without KANON_HOME, .packages/ must be removed from $HOME/.kanon/store"
        )
        assert not (store / ".kanon-data").exists(), (
            "Without KANON_HOME, .kanon-data/ must be removed from $HOME/.kanon/store"
        )

    def test_clean_prunes_content_addressed_store_entries(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-52: clean prunes the content-addressed store entries in addition to per-project artifacts."""
        from kanon_cli.core.install import store_entries_dir

        kanon_home = tmp_path / "home"
        store = kanon_home / "store"
        cwd_dir = tmp_path / "project"
        cwd_dir.mkdir()

        kanonenv = cwd_dir / ".kanon"
        kanonenv.write_text(_MINIMAL_KANONENV)

        # A published content-addressed entry (as install would have written).
        entry = store_entries_dir(store) / ("a" * 64)
        entry.mkdir(parents=True)
        (entry / "payload").write_text("data")
        (store / ".packages").mkdir(parents=True)
        (store / ".kanon-data").mkdir(parents=True)

        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not entry.exists(), "the content-addressed store entry must be pruned by clean"
        assert not store_entries_dir(store).exists(), "the store entries directory must be pruned by clean"
        assert store.exists(), "the store base directory must survive clean"


# ---------------------------------------------------------------------------
# clean(orphans=...) ledger-driven marketplace pruning
# ---------------------------------------------------------------------------


def _make_source(name: str, *, registered_marketplaces: list[str]) -> SourceEntry:
    """Build a valid SourceEntry carrying a per-source marketplace ledger."""
    return SourceEntry(
        alias=name,
        name=name,
        url=f"https://example.com/{name}.git",
        ref_spec="main",
        resolved_ref="refs/heads/main",
        resolved_sha="a" * 40,
        path=f"repo-specs/{name}.xml",
        registered_marketplaces=registered_marketplaces,
    )


def _write_lock(
    base_dir: pathlib.Path,
    *,
    marketplace_dir: pathlib.Path,
    sources: list[SourceEntry],
) -> pathlib.Path:
    """Write a real schema-v4 .kanon.lock with per-source marketplace ledgers.

    Schema v4 carries no [catalog] block; the hash is synthetic-but-valid so
    read_lockfile parses the file without raising. Returns the lockfile path.
    """
    lockfile = Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        generator="kanon-cli/test",
        kanon_hash="sha256:" + ("a" * 64),
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
    """Write a .kanon declaring the given source names (marketplace install on).

    Each source opts into marketplace install via its per-dependency
    KANON_SOURCE_<name>_MARKETPLACE=true flag (spec Section 5.1 / FR-17).
    """
    lines = [
        f"CLAUDE_MARKETPLACES_DIR={marketplace_dir}",
    ]
    for name in source_names:
        lines.append(f"KANON_SOURCE_{name}_URL=https://example.com/{name}.git")
        lines.append(f"KANON_SOURCE_{name}_REF=main")
        lines.append(f"KANON_SOURCE_{name}_PATH=repo-specs/{name}.xml")
        lines.append(f"KANON_SOURCE_{name}_NAME={name}")
        lines.append(f"KANON_SOURCE_{name}_GITBASE=https://example.com")
        lines.append(f"KANON_SOURCE_{name}_MARKETPLACE=true")
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

        _write_lock(
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

        _write_lock(
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

        _write_lock(
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

        _write_lock(
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

        _write_lock(
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
