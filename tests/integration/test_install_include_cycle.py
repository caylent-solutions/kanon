"""Integration tests for <include> cycle detection during kanon install.

AC-TEST-002: Integration test with a three-XML triangle cycle fixture.
AC-CYCLE-001(a): kanon install exits non-zero with IncludeCycleError and the
rendered cycle string.

The fixture creates three manifest XML files in a temporary source workspace
that simulates the checked-out manifest repo after repo sync:
  - a.xml includes b.xml
  - b.xml includes c.xml
  - c.xml includes a.xml (closes the triangle)

When install() is called with this fixture, it must raise IncludeCycleError
before any lockfile is written.
"""

from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest

from kanon_cli.core.include_walker import IncludeCycleError
from kanon_cli.core.install import install, resolve_workspace_base_dir


def _write_manifest(path: pathlib.Path, includes: list[str]) -> None:
    """Write a minimal <manifest> XML with the given <include name=...> elements."""
    root = ET.Element("manifest")
    for name in includes:
        ET.SubElement(root, "include", name=name)
    ET.ElementTree(root).write(str(path), encoding="unicode", xml_declaration=False)


def _write_kanonenv(directory: pathlib.Path, manifest_path: str) -> pathlib.Path:
    """Write a minimal .kanon file referencing the given manifest XML path."""
    kanonenv = directory / ".kanon"
    kanonenv.write_text(
        "KANON_MARKETPLACE_INSTALL=false\n"
        "KANON_SOURCE_test_URL=https://example.com/manifest.git\n"
        "KANON_SOURCE_test_REF=main\n"
        f"KANON_SOURCE_test_PATH={manifest_path}\n"
        "KANON_SOURCE_test_NAME=test\n"
        "KANON_SOURCE_test_GITBASE=https://example.com\n"
    )
    return kanonenv.resolve()


def _run_install_with_fixture_sync(
    kanonenv: pathlib.Path,
    fixture_source_dir: pathlib.Path,
) -> None:
    """Run install() with repo operations patched to materialise the fixture source dir.

    The fake repo_sync copies nothing (XML files are pre-written in fixture_source_dir),
    while repo_init and repo_envsubst are no-ops.  The source dir is pre-populated
    with the fixture XML files so _walk_includes sees the triangle cycle.

    Args:
        kanonenv: Path to the .kanon configuration file.
        fixture_source_dir: Pre-populated source directory containing the XML fixtures.
    """
    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
    ):
        # install is hermetic in 3.0.0: it takes no catalog source (it never
        # resolves a remote catalog). The conftest autouse fixture mocks
        # _resolve_ref_to_sha so source refs are resolved without network.
        install(
            kanonenv,
            lock_file_path=kanonenv.parent / ".kanon.lock",
        )


@pytest.mark.integration
class TestInstallIncludeCycleTriangle:
    """Triangle-cycle fixture exercising install() end-to-end: A -> B -> C -> A."""

    def _build_triangle_fixture(
        self,
        base: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> tuple[pathlib.Path, pathlib.Path]:
        """Create .kanon and triangle XML files; return (kanonenv, source_dir).

        The source dir is the directory that simulates the post-sync checkout.
        In the 3.0.0 store model (spec Section 7.1 / FR-15) install materialises
        it under ``<KANON_HOME>/store/.kanon-data/sources/test/``. KANON_HOME is
        pinned to ``base/home`` and the fixture XML files are pre-populated there
        so that when _walk_includes runs it finds the triangle cycle.
        """
        # Write the .kanon file in the project dir.
        kanonenv = _write_kanonenv(base, manifest_path="a.xml")

        # Pin KANON_HOME so the artifact store resolves under base.
        kanon_home = base / "home"
        kanon_home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("KANON_HOME", str(kanon_home))
        store = resolve_workspace_base_dir()

        # Pre-populate the manifest checkout directory that install() will use.
        # After real repo init + repo sync, manifests live at
        # <store>/.kanon-data/sources/test/.repo/manifests/; pre-populate that
        # path so _walk_includes finds the fixture files where the code expects.
        source_dir = store / ".kanon-data" / "sources" / "test"
        manifest_repo = source_dir / ".repo" / "manifests"
        manifest_repo.mkdir(parents=True, exist_ok=True)

        _write_manifest(manifest_repo / "a.xml", includes=["b.xml"])
        _write_manifest(manifest_repo / "b.xml", includes=["c.xml"])
        _write_manifest(manifest_repo / "c.xml", includes=["a.xml"])

        return kanonenv, source_dir

    def test_triangle_raises_include_cycle_error(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """install() raises IncludeCycleError on a triangle-cycle fixture."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path, monkeypatch)
        with pytest.raises(IncludeCycleError):
            _run_install_with_fixture_sync(kanonenv, source_dir)

    def test_triangle_error_message_contains_all_nodes(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """IncludeCycleError from install() names every node in the triangle."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path, monkeypatch)
        with pytest.raises(IncludeCycleError) as exc_info:
            _run_install_with_fixture_sync(kanonenv, source_dir)
        msg = str(exc_info.value)
        assert "a.xml" in msg
        assert "b.xml" in msg
        assert "c.xml" in msg

    def test_triangle_error_message_prefix(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """IncludeCycleError message from install() starts with 'include cycle:'."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path, monkeypatch)
        with pytest.raises(IncludeCycleError) as exc_info:
            _run_install_with_fixture_sync(kanonenv, source_dir)
        assert str(exc_info.value).startswith("include cycle:")

    def test_triangle_error_message_closes_cycle(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """IncludeCycleError from install() renders the closing edge (a.xml appears twice)."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path, monkeypatch)
        with pytest.raises(IncludeCycleError) as exc_info:
            _run_install_with_fixture_sync(kanonenv, source_dir)
        msg = str(exc_info.value)
        assert msg.count("a.xml") >= 2

    def test_triangle_error_uses_repo_relative_paths(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """IncludeCycleError from install() uses repo-relative paths, not absolute paths."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path, monkeypatch)
        with pytest.raises(IncludeCycleError) as exc_info:
            _run_install_with_fixture_sync(kanonenv, source_dir)
        msg = str(exc_info.value)
        assert str(tmp_path) not in msg

    def test_triangle_arrow_separator(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """IncludeCycleError from install() separates path nodes with ' -> '."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path, monkeypatch)
        with pytest.raises(IncludeCycleError) as exc_info:
            _run_install_with_fixture_sync(kanonenv, source_dir)
        msg = str(exc_info.value)
        assert " -> " in msg

    def test_triangle_no_lockfile_written(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """install() writes no lockfile when IncludeCycleError is raised."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path, monkeypatch)
        with pytest.raises(IncludeCycleError):
            _run_install_with_fixture_sync(kanonenv, source_dir)
        lockfile_path = tmp_path / ".kanon.lock"
        assert not lockfile_path.exists(), "no lockfile should be written on cycle error"


@pytest.mark.integration
class TestInstallIncludeSelfCycle:
    """Self-cycle fixture exercising install() end-to-end: A -> A."""

    def test_self_cycle_raises(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """install() raises IncludeCycleError for a self-referencing include."""
        kanonenv = _write_kanonenv(tmp_path, manifest_path="a.xml")
        kanon_home = tmp_path / "home"
        kanon_home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("KANON_HOME", str(kanon_home))
        source_dir = resolve_workspace_base_dir() / ".kanon-data" / "sources" / "test"
        manifest_repo = source_dir / ".repo" / "manifests"
        manifest_repo.mkdir(parents=True, exist_ok=True)
        _write_manifest(manifest_repo / "a.xml", includes=["a.xml"])

        with pytest.raises(IncludeCycleError) as exc_info:
            _run_install_with_fixture_sync(kanonenv, source_dir)

        msg = str(exc_info.value)
        assert "include cycle:" in msg
        assert "a.xml" in msg
        assert msg.count("a.xml") >= 2
