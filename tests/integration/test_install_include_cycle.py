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
from kanon_cli.core.install import install


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
        # A dummy catalog_source is required so install() does not raise
        # MissingCatalogSourceError before reaching the include-walk step.
        # The conftest autouse fixture mocks _resolve_ref_to_sha so the
        # catalog URL is never actually queried.
        install(
            kanonenv,
            lock_file_path=kanonenv.parent / ".kanon.lock",
            catalog_source="https://example.com/catalog.git@main",
        )


@pytest.mark.integration
class TestInstallIncludeCycleTriangle:
    """Triangle-cycle fixture exercising install() end-to-end: A -> B -> C -> A."""

    def _build_triangle_fixture(
        self,
        base: pathlib.Path,
    ) -> tuple[pathlib.Path, pathlib.Path]:
        """Create .kanon and triangle XML files; return (kanonenv, source_dir).

        The source dir is the directory that simulates the post-sync checkout.
        install() creates it under .kanon-data/sources/test/ in base.
        We pre-populate it so that when _walk_includes runs, it finds the files.
        """
        # Write the .kanon file.
        kanonenv = _write_kanonenv(base, manifest_path="a.xml")

        # Pre-populate the manifest checkout directory that install() will use.
        # After real repo init + repo sync, manifests live at
        # source_dir/.repo/manifests/; pre-populate that path so _walk_includes
        # finds the fixture files in the same location the production code expects.
        source_dir = base / ".kanon-data" / "sources" / "test"
        manifest_repo = source_dir / ".repo" / "manifests"
        manifest_repo.mkdir(parents=True, exist_ok=True)

        _write_manifest(manifest_repo / "a.xml", includes=["b.xml"])
        _write_manifest(manifest_repo / "b.xml", includes=["c.xml"])
        _write_manifest(manifest_repo / "c.xml", includes=["a.xml"])

        return kanonenv, source_dir

    def test_triangle_raises_include_cycle_error(self, tmp_path: pathlib.Path) -> None:
        """install() raises IncludeCycleError on a triangle-cycle fixture."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path)
        with pytest.raises(IncludeCycleError):
            _run_install_with_fixture_sync(kanonenv, source_dir)

    def test_triangle_error_message_contains_all_nodes(self, tmp_path: pathlib.Path) -> None:
        """IncludeCycleError from install() names every node in the triangle."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path)
        with pytest.raises(IncludeCycleError) as exc_info:
            _run_install_with_fixture_sync(kanonenv, source_dir)
        msg = str(exc_info.value)
        assert "a.xml" in msg
        assert "b.xml" in msg
        assert "c.xml" in msg

    def test_triangle_error_message_prefix(self, tmp_path: pathlib.Path) -> None:
        """IncludeCycleError message from install() starts with 'include cycle:'."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path)
        with pytest.raises(IncludeCycleError) as exc_info:
            _run_install_with_fixture_sync(kanonenv, source_dir)
        assert str(exc_info.value).startswith("include cycle:")

    def test_triangle_error_message_closes_cycle(self, tmp_path: pathlib.Path) -> None:
        """IncludeCycleError from install() renders the closing edge (a.xml appears twice)."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path)
        with pytest.raises(IncludeCycleError) as exc_info:
            _run_install_with_fixture_sync(kanonenv, source_dir)
        msg = str(exc_info.value)
        assert msg.count("a.xml") >= 2

    def test_triangle_error_uses_repo_relative_paths(self, tmp_path: pathlib.Path) -> None:
        """IncludeCycleError from install() uses repo-relative paths, not absolute paths."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path)
        with pytest.raises(IncludeCycleError) as exc_info:
            _run_install_with_fixture_sync(kanonenv, source_dir)
        msg = str(exc_info.value)
        assert str(tmp_path) not in msg

    def test_triangle_arrow_separator(self, tmp_path: pathlib.Path) -> None:
        """IncludeCycleError from install() separates path nodes with ' -> '."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path)
        with pytest.raises(IncludeCycleError) as exc_info:
            _run_install_with_fixture_sync(kanonenv, source_dir)
        msg = str(exc_info.value)
        assert " -> " in msg

    def test_triangle_no_lockfile_written(self, tmp_path: pathlib.Path) -> None:
        """install() writes no lockfile when IncludeCycleError is raised."""
        kanonenv, source_dir = self._build_triangle_fixture(tmp_path)
        with pytest.raises(IncludeCycleError):
            _run_install_with_fixture_sync(kanonenv, source_dir)
        lockfile_path = tmp_path / ".kanon.lock"
        assert not lockfile_path.exists(), "no lockfile should be written on cycle error"


@pytest.mark.integration
class TestInstallIncludeSelfCycle:
    """Self-cycle fixture exercising install() end-to-end: A -> A."""

    def test_self_cycle_raises(self, tmp_path: pathlib.Path) -> None:
        """install() raises IncludeCycleError for a self-referencing include."""
        kanonenv = _write_kanonenv(tmp_path, manifest_path="a.xml")
        source_dir = tmp_path / ".kanon-data" / "sources" / "test"
        manifest_repo = source_dir / ".repo" / "manifests"
        manifest_repo.mkdir(parents=True, exist_ok=True)
        _write_manifest(manifest_repo / "a.xml", includes=["a.xml"])

        with pytest.raises(IncludeCycleError) as exc_info:
            _run_install_with_fixture_sync(kanonenv, source_dir)

        msg = str(exc_info.value)
        assert "include cycle:" in msg
        assert "a.xml" in msg
        assert msg.count("a.xml") >= 2
