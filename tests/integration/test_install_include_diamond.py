"""Integration tests for <include> diamond handling during kanon install.

AC-TEST-003: Integration test with a four-XML diamond fixture.
AC-CYCLE-001(b): kanon install succeeds with diamond; the resulting lockfile
has the shared XML appearing exactly once in the include tree.

Diamond structure:
  a.xml includes [b.xml, c.xml]
  b.xml includes [d.xml]
  c.xml includes [d.xml]   <- d.xml visited a second time via c
  d.xml has no includes

After install() resolves the diamond, d.xml must appear exactly once in the
lockfile's include tree (under b.xml, its first-walked position).  The lockfile
is written at .kanon.lock in the project root.
"""

from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest

from kanon_cli.core.install import install
from kanon_cli.core.lockfile import read_lockfile


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
        "KANON_SOURCE_test_REVISION=main\n"
        f"KANON_SOURCE_test_PATH={manifest_path}\n"
    )
    return kanonenv.resolve()


def _run_install_with_fixture_sync(
    kanonenv: pathlib.Path,
) -> None:
    """Run install() with repo operations patched to no-ops.

    The source dir must be pre-populated before calling this function so that
    _walk_includes finds the fixture XML files after the (no-op) repo sync.

    Args:
        kanonenv: Path to the .kanon configuration file.
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


def _count_include_entries(entries: list) -> int:
    """Count total IncludeEntry nodes in a nested list (recursive pre-order)."""
    total = 0
    for entry in entries:
        total += 1 + _count_include_entries(entry.includes)
    return total


def _collect_include_paths(entries: list) -> list[str]:
    """Collect path_in_repo values from all IncludeEntry nodes in DFS pre-order."""
    result: list[str] = []
    for entry in entries:
        result.append(entry.path_in_repo)
        result.extend(_collect_include_paths(entry.includes))
    return result


@pytest.mark.integration
class TestInstallIncludeDiamond:
    """Four-node diamond fixture exercising install() end-to-end.

    Diamond: A -> [B, C]; B -> D; C -> D.
    After install(), the lockfile must contain D exactly once under B.
    """

    def _build_diamond_fixture(
        self,
        base: pathlib.Path,
    ) -> tuple[pathlib.Path, pathlib.Path]:
        """Create .kanon and diamond XML files; return (kanonenv, source_dir).

        The source dir is pre-populated to simulate the post-sync checkout.
        """
        kanonenv = _write_kanonenv(base, manifest_path="a.xml")

        # Pre-populate the manifest checkout directory that install() will use.
        # After real repo init + repo sync, manifests live at
        # source_dir/.repo/manifests/; pre-populate that path so _walk_includes
        # finds the fixture files in the same location the production code expects.
        source_dir = base / ".kanon-data" / "sources" / "test"
        manifest_repo = source_dir / ".repo" / "manifests"
        manifest_repo.mkdir(parents=True, exist_ok=True)

        _write_manifest(manifest_repo / "a.xml", includes=["b.xml", "c.xml"])
        _write_manifest(manifest_repo / "b.xml", includes=["d.xml"])
        _write_manifest(manifest_repo / "c.xml", includes=["d.xml"])
        _write_manifest(manifest_repo / "d.xml", includes=[])

        return kanonenv, source_dir

    def test_diamond_install_succeeds(self, tmp_path: pathlib.Path) -> None:
        """install() does NOT raise for a diamond-shaped include fixture."""
        kanonenv, _source_dir = self._build_diamond_fixture(tmp_path)
        # Must not raise -- diamond is a valid (non-cyclic) structure.
        _run_install_with_fixture_sync(kanonenv)

    def test_diamond_lockfile_written(self, tmp_path: pathlib.Path) -> None:
        """install() writes a lockfile when the diamond fixture succeeds."""
        kanonenv, _source_dir = self._build_diamond_fixture(tmp_path)
        _run_install_with_fixture_sync(kanonenv)
        lockfile_path = tmp_path / ".kanon.lock"
        assert lockfile_path.exists(), "lockfile must be written after successful install"

    def test_diamond_d_appears_exactly_once_in_lockfile(self, tmp_path: pathlib.Path) -> None:
        """d.xml appears exactly once in the lockfile's include tree."""
        kanonenv, _source_dir = self._build_diamond_fixture(tmp_path)
        _run_install_with_fixture_sync(kanonenv)

        lockfile_path = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lockfile_path)

        assert len(lockfile.sources) == 1
        source = lockfile.sources[0]

        # Collect all path_in_repo values from the include tree.
        all_paths = _collect_include_paths(source.includes)
        d_count = sum(1 for p in all_paths if p == "d.xml")
        assert d_count == 1, f"d.xml appeared {d_count} times in lockfile; expected exactly 1"

    def test_diamond_lockfile_include_count(self, tmp_path: pathlib.Path) -> None:
        """The lockfile contains 3 include entries total (b, d under b, c -- d deduped)."""
        kanonenv, _source_dir = self._build_diamond_fixture(tmp_path)
        _run_install_with_fixture_sync(kanonenv)

        lockfile_path = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lockfile_path)

        source = lockfile.sources[0]
        total_includes = _count_include_entries(source.includes)
        # b + d (under b) + c = 3 entries (d is not repeated under c)
        assert total_includes == 3, f"expected 3 include entries (b, d, c); got {total_includes}"

    def test_diamond_d_under_b_not_c(self, tmp_path: pathlib.Path) -> None:
        """d.xml is a child of b.xml (first-walked position), not of c.xml."""
        kanonenv, _source_dir = self._build_diamond_fixture(tmp_path)
        _run_install_with_fixture_sync(kanonenv)

        lockfile_path = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lockfile_path)

        source = lockfile.sources[0]
        # source.includes == [b_entry, c_entry]
        assert len(source.includes) == 2
        b_entry = source.includes[0]
        c_entry = source.includes[1]

        # d is a child of b
        b_child_paths = [e.path_in_repo for e in b_entry.includes]
        assert "d.xml" in b_child_paths, "d.xml must appear under b.xml in lockfile"

        # d is NOT a child of c (diamond-deduped)
        c_child_paths = [e.path_in_repo for e in c_entry.includes]
        assert "d.xml" not in c_child_paths, "d.xml must NOT appear under c.xml (deduped)"

    def test_diamond_c_has_no_children_in_lockfile(self, tmp_path: pathlib.Path) -> None:
        """After diamond dedup, c.xml has zero child includes in the lockfile."""
        kanonenv, _source_dir = self._build_diamond_fixture(tmp_path)
        _run_install_with_fixture_sync(kanonenv)

        lockfile_path = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lockfile_path)

        source = lockfile.sources[0]
        c_entry = source.includes[1]
        assert c_entry.includes == [], "c.xml must have no child includes in lockfile"

    def test_diamond_dfs_order_in_lockfile(self, tmp_path: pathlib.Path) -> None:
        """Lockfile include order matches DFS pre-order: b, d (under b), c."""
        kanonenv, _source_dir = self._build_diamond_fixture(tmp_path)
        _run_install_with_fixture_sync(kanonenv)

        lockfile_path = tmp_path / ".kanon.lock"
        lockfile = read_lockfile(lockfile_path)

        source = lockfile.sources[0]
        all_paths = _collect_include_paths(source.includes)
        # DFS pre-order: b, d (child of b), c
        assert all_paths[0] == "b.xml"
        assert all_paths[1] == "d.xml"
        assert all_paths[2] == "c.xml"
        assert len(all_paths) == 3
