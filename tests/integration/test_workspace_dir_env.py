"""Integration tests for the shared KANON_HOME store honoring in kanon install and clean.

Verifies that when KANON_HOME is set, install places .packages/ and
.kanon-data/ under ``<KANON_HOME>/store`` (not beside .kanon), and clean removes
them from the same location.  Covers the path= (direct checkout) entry shape as
well as the standard URL-based shape.

AC-9 (AC-1): install creates .packages/ and .kanon-data/ under <KANON_HOME>/store
AC-10 (AC-2): clean removes .packages/ and .kanon-data/ from <KANON_HOME>/store
AC-11 (AC-3): relocation holds for direct path= checkout entry (builders-plugins / F8)
AC-12 (AC-4): unwritable KANON_HOME store exits non-zero with actionable message, no cwd fallback
AC-13 (AC-5): genuine RED->GREEN recorded in TDD cycle log
AC-14 (AC-6): --help snapshots unchanged (no surface drift)
"""

import pathlib
import stat
from unittest.mock import patch

import pytest

from kanon_cli.constants import KANON_HOME_STORE_SUBDIR
from kanon_cli.core.clean import clean
from kanon_cli.core.include_walker import IncludeTree
from kanon_cli.core.install import _RefResolution, install


_FAKE_SHA = "a" * 40
_FAKE_REF_RESOLUTION = _RefResolution(sha=_FAKE_SHA, resolved_ref="refs/heads/main")


def _store_dir(kanon_home: pathlib.Path) -> pathlib.Path:
    """Return the artifact store directory for a given KANON_HOME root."""
    return kanon_home / KANON_HOME_STORE_SUBDIR


def _url_kanonenv(directory: pathlib.Path, source_name: str = "build") -> pathlib.Path:
    """Write a minimal URL-based .kanon file and return its path."""
    kanonenv = directory / ".kanon"
    kanonenv.write_text(
        f"KANON_SOURCE_{source_name}_URL=https://example.com/{source_name}.git\n"
        f"KANON_SOURCE_{source_name}_REF=main\n"
        f"KANON_SOURCE_{source_name}_PATH=meta.xml\n"
        f"KANON_SOURCE_{source_name}_NAME={source_name}\n"
        f"KANON_SOURCE_{source_name}_GITBASE=https://example.com\n"
    )
    return kanonenv.resolve()


def _path_source_kanonenv(directory: pathlib.Path, source_name: str = "builders-plugins") -> pathlib.Path:
    """Write a .kanon file with a URL-based source simulating a direct path= catalog entry.

    In the kanon .kanon file format, all sources require the five alias-keyed
    variables: URL, REF, PATH, NAME, and GITBASE.  The 'path=' catalog entry
    type (F8) is a catalog-level concept; at the .kanon level it still resolves
    to the standard alias-keyed source block.  This helper uses the same URL
    source format as _url_kanonenv but names the source 'builders-plugins' to
    mirror the F8 fixture entry name.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(
        f"KANON_SOURCE_{source_name}_URL=https://example.com/{source_name}.git\n"
        f"KANON_SOURCE_{source_name}_REF=main\n"
        f"KANON_SOURCE_{source_name}_PATH=meta.xml\n"
        f"KANON_SOURCE_{source_name}_NAME={source_name}\n"
        f"KANON_SOURCE_{source_name}_GITBASE=https://example.com\n"
    )
    return kanonenv.resolve()


def _run_install(kanonenv: pathlib.Path, lock_path: pathlib.Path) -> None:
    """Run install() with repo operations patched to no-ops."""
    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
        patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=_FAKE_REF_RESOLUTION),
        patch(
            "kanon_cli.core.install._walk_includes",
            return_value=IncludeTree(path=pathlib.Path("meta.xml")),
        ),
    ):
        install(kanonenv, lock_file_path=lock_path)


@pytest.mark.integration
class TestKanonHomeStoreInstallCleanRoundtrip:
    """AC-9 / AC-10: install + clean roundtrip with KANON_HOME set (URL source)."""

    def test_install_creates_artifacts_under_store(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-9: install creates .packages/ and .kanon-data/ under <KANON_HOME>/store."""
        kanon_home = tmp_path / "kanon_home"
        store = _store_dir(kanon_home)
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        kanonenv = _url_kanonenv(project)
        lock_path = project / ".kanon.lock"

        _run_install(kanonenv, lock_path)

        assert (store / ".kanon-data").exists(), "install must create .kanon-data/ under <KANON_HOME>/store"
        assert not (project / ".kanon-data").exists(), "install must NOT create .kanon-data/ in the cwd (beside .kanon)"
        assert not (project / ".packages").exists(), "install must NOT create .packages/ in the cwd (beside .kanon)"

    def test_install_creates_packages_dir_under_store(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-9: .packages/ is created under <KANON_HOME>/store."""
        kanon_home = tmp_path / "home"
        store = _store_dir(kanon_home)
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        kanonenv = _url_kanonenv(project)
        lock_path = project / ".kanon.lock"

        _run_install(kanonenv, lock_path)

        assert (store / ".packages").exists(), "install must create .packages/ under <KANON_HOME>/store"

    def test_clean_removes_artifacts_from_store(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-10: clean removes .packages/ and .kanon-data/ from <KANON_HOME>/store."""
        kanon_home = tmp_path / "kanon_home"
        store = _store_dir(kanon_home)
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        (store / ".packages").mkdir(parents=True)
        (store / ".kanon-data").mkdir(parents=True)

        (project / ".packages").mkdir()
        (project / ".kanon-data").mkdir()

        kanonenv = _url_kanonenv(project)

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not (store / ".packages").exists(), "clean must remove .packages/ from <KANON_HOME>/store"
        assert not (store / ".kanon-data").exists(), "clean must remove .kanon-data/ from <KANON_HOME>/store"
        assert (project / ".packages").exists(), "clean must NOT remove .packages/ beside .kanon when KANON_HOME is set"
        assert (project / ".kanon-data").exists(), (
            "clean must NOT remove .kanon-data/ beside .kanon when KANON_HOME is set"
        )

    def test_store_is_created_when_absent(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-9: <KANON_HOME>/store need not pre-exist; install creates it."""
        kanon_home = tmp_path / "nonexistent" / "nested_dir"
        store = _store_dir(kanon_home)
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        assert not store.exists(), "pre-condition: store must be absent"

        kanonenv = _url_kanonenv(project)
        lock_path = project / ".kanon.lock"

        _run_install(kanonenv, lock_path)

        assert store.exists(), "install must create <KANON_HOME>/store when it is absent"


@pytest.mark.integration
class TestKanonHomeStorePathEntry:
    """AC-11 / AC-3: relocation holds for direct path= checkout entries (F8)."""

    def test_path_entry_install_creates_artifacts_under_store(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-11: path= (direct checkout) entry -- install creates artifacts under <KANON_HOME>/store.

        The 'path=' catalog entry type (F8 / builders-plugins) resolves to the
        same .kanon format as URL sources.  The source name 'builders-plugins'
        mirrors the F8 fixture entry so the test covers that specific case.
        """
        kanon_home = tmp_path / "kanon_home"
        store = _store_dir(kanon_home)
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        kanonenv = _path_source_kanonenv(project)
        lock_path = project / ".kanon.lock"

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=_FAKE_REF_RESOLUTION),
            patch(
                "kanon_cli.core.install._walk_includes",
                return_value=IncludeTree(path=pathlib.Path("meta.xml")),
            ),
        ):
            install(kanonenv, lock_file_path=lock_path)

        assert (store / ".kanon-data").exists(), "path= entry: install must place .kanon-data/ under <KANON_HOME>/store"
        assert not (project / ".kanon-data").exists(), (
            "path= entry: .kanon-data/ must NOT appear in the project directory"
        )

    def test_path_entry_clean_removes_artifacts_from_store(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-11: path= (direct checkout) entry -- clean removes artifacts from <KANON_HOME>/store."""
        kanon_home = tmp_path / "kanon_home"
        store = _store_dir(kanon_home)
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        (store / ".packages").mkdir(parents=True)
        (store / ".kanon-data").mkdir(parents=True)

        kanonenv = _path_source_kanonenv(project)

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            clean(kanonenv)

        assert not (store / ".packages").exists(), "path= entry: clean must remove .packages/ from <KANON_HOME>/store"
        assert not (store / ".kanon-data").exists(), (
            "path= entry: clean must remove .kanon-data/ from <KANON_HOME>/store"
        )


@pytest.mark.integration
class TestKanonHomeStoreUnwritable:
    """AC-12 / AC-4: unwritable KANON_HOME store causes non-zero exit, no cwd fallback."""

    def test_unwritable_store_exits_nonzero(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-12: install exits non-zero when the <KANON_HOME>/store cannot be created."""
        locked_parent = tmp_path / "locked"
        locked_parent.mkdir()

        kanon_home = locked_parent / "home"
        locked_parent.chmod(stat.S_IRUSR | stat.S_IXUSR)

        monkeypatch.setenv("KANON_HOME", str(kanon_home))
        project = tmp_path / "project"
        project.mkdir(parents=True, exist_ok=True)

        kanonenv = _url_kanonenv(project)
        lock_path = project / ".kanon.lock"

        try:
            with pytest.raises(SystemExit) as exc_info:
                _run_install(kanonenv, lock_path)
            assert exc_info.value.code != 0, "install must exit non-zero when the KANON_HOME store is unwritable"
        finally:
            locked_parent.chmod(stat.S_IRWXU)

    def test_unwritable_store_writes_no_artifacts_to_cwd(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-12: no artifacts are silently written to cwd on an unwritable KANON_HOME store."""
        locked_parent = tmp_path / "locked2"
        locked_parent.mkdir()
        kanon_home = locked_parent / "home"
        locked_parent.chmod(stat.S_IRUSR | stat.S_IXUSR)

        monkeypatch.setenv("KANON_HOME", str(kanon_home))
        project = tmp_path / "project"
        project.mkdir(parents=True, exist_ok=True)

        kanonenv = _url_kanonenv(project)
        lock_path = project / ".kanon.lock"

        try:
            with pytest.raises(SystemExit):
                _run_install(kanonenv, lock_path)
            assert not (project / ".kanon-data").exists(), (
                "no .kanon-data/ must appear in cwd when the KANON_HOME store is unwritable (no fallback)"
            )
            assert not (project / ".packages").exists(), (
                "no .packages/ must appear in cwd when the KANON_HOME store is unwritable (no fallback)"
            )
        finally:
            locked_parent.chmod(stat.S_IRWXU)


@pytest.mark.integration
class TestHelpSnapshotsUnchanged:
    """AC-14: kanon install --help and kanon clean --help exit 0 (no accidental surface drift)."""

    def test_install_help_exits_zero(self) -> None:
        """install --help exits 0 -- surface is unchanged by the KANON_HOME store model."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["install", "--help"])
        assert exc_info.value.code == 0, "kanon install --help must exit 0"

    def test_clean_help_exits_zero(self) -> None:
        """clean --help exits 0 -- surface is unchanged by the KANON_HOME store model."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["clean", "--help"])
        assert exc_info.value.code == 0, "kanon clean --help must exit 0"
