"""Tests for the catalog-declared <min-kanon-version> and how kanon add writes it into .kanon."""

import argparse
import pathlib
import textwrap
from unittest.mock import patch

import pytest
from packaging.version import Version

from kanon_cli import __version__
from kanon_cli.commands.add import run_add
from kanon_cli.constants import KANON_CATALOG_MIN_VERSION_TAG, KANON_MIN_VERSION_KEY
from kanon_cli.core.kanonenv_writer import upsert_min_version
from kanon_cli.core.metadata import CatalogMetadata, _parse_catalog_metadata, audit_catalog_metadata
from kanon_cli.core.min_version import KanonVersionTooOldError

_NEXT_MAJOR = f"{Version(__version__).major + 1}.0.0"
_ENTRY_URL = "https://example.com/org/manifests.git"


def _catalog_xml(min_version_element: str) -> str:
    return textwrap.dedent(f"""\
        <?xml version="1.0"?>
        <manifest>
          <catalog-metadata>
            <name>my-tool</name>
            <display-name>My Tool</display-name>
            <description>A useful tool.</description>
            <version>1.0.0</version>
            <type>plugin</type>
            <owner-name>Alice</owner-name>
            <owner-email>alice@example.com</owner-email>
            <keywords>infra</keywords>
            {min_version_element}
          </catalog-metadata>
        </manifest>
    """)


def _write(path: pathlib.Path, content: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.unit
class TestParseCatalogMinVersion:
    def test_declared_value_is_parsed(self, tmp_path: pathlib.Path) -> None:
        xml = _write(tmp_path / "e.xml", _catalog_xml("<min-kanon-version> 3.4.2 </min-kanon-version>"))
        assert _parse_catalog_metadata(xml).min_kanon_version == "3.4.2"

    @pytest.mark.parametrize("element", ["", "<min-kanon-version></min-kanon-version>"])
    def test_absent_or_blank_is_none_without_warning(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], element: str
    ) -> None:
        xml = _write(tmp_path / "e.xml", _catalog_xml(element))
        assert _parse_catalog_metadata(xml).min_kanon_version is None
        assert KANON_CATALOG_MIN_VERSION_TAG not in capsys.readouterr().err

    def test_invalid_value_does_not_break_parsing(self, tmp_path: pathlib.Path) -> None:
        """Listing a catalog must survive one bad entry; add and the audit reject it instead."""
        xml = _write(tmp_path / "e.xml", _catalog_xml("<min-kanon-version>latest</min-kanon-version>"))
        assert _parse_catalog_metadata(xml).min_kanon_version == "latest"


@pytest.mark.unit
class TestAuditCatalogMinVersion:
    @pytest.mark.parametrize("value", ["latest", ">=3.4.2", "3.4.x"])
    def test_invalid_value_is_an_m008_error(self, tmp_path: pathlib.Path, value: str) -> None:
        xml = _write(tmp_path / "e.xml", _catalog_xml(f"<min-kanon-version>{value}</min-kanon-version>"))
        issues = audit_catalog_metadata(xml)
        assert [(i.severity, i.code) for i in issues] == [("error", "M008")]
        assert repr(value) in issues[0].message
        assert str(xml) in issues[0].message

    @pytest.mark.parametrize("element", ["", "<min-kanon-version>3.4.2</min-kanon-version>"])
    def test_valid_or_absent_value_has_no_issue(self, tmp_path: pathlib.Path, element: str) -> None:
        xml = _write(tmp_path / "e.xml", _catalog_xml(element))
        assert audit_catalog_metadata(xml) == []


@pytest.mark.unit
class TestUpsertMinVersion:
    def test_creates_file_when_absent(self, tmp_path: pathlib.Path) -> None:
        kanon_file = tmp_path / ".kanon"
        upsert_min_version(kanon_file, "3.4.2", hold_lock=False)
        assert kanon_file.read_text(encoding="utf-8") == f"{KANON_MIN_VERSION_KEY}=3.4.2\n"

    def test_inserts_after_leading_comments_with_separator(self, tmp_path: pathlib.Path) -> None:
        kanon_file = _write(tmp_path / ".kanon", "# project\nKANON_SOURCE_a_URL=u\n")
        upsert_min_version(kanon_file, "3.4.2", hold_lock=False)
        assert kanon_file.read_text(encoding="utf-8") == (
            f"# project\n{KANON_MIN_VERSION_KEY}=3.4.2\n\nKANON_SOURCE_a_URL=u\n"
        )

    def test_replaces_existing_line_in_place_keeping_crlf(self, tmp_path: pathlib.Path) -> None:
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_bytes(f"A=1\r\n{KANON_MIN_VERSION_KEY}=3.0.0\r\nB=2\r\n".encode())
        upsert_min_version(kanon_file, "3.4.2", hold_lock=False)
        assert kanon_file.read_bytes() == f"A=1\r\n{KANON_MIN_VERSION_KEY}=3.4.2\r\nB=2\r\n".encode()

    def test_holds_workspace_lock_by_default(self, tmp_path: pathlib.Path) -> None:
        kanon_file = tmp_path / ".kanon"
        with patch("kanon_cli.core.kanonenv_writer.kanon_workspace_lock") as lock_mock:
            upsert_min_version(kanon_file, "3.4.2")
        lock_mock.assert_called_once()


def _metadata(name: str, min_kanon_version: str | None) -> CatalogMetadata:
    return CatalogMetadata(
        name=name,
        display_name=name,
        description=f"Description of {name}.",
        version="1.0.0",
        min_kanon_version=min_kanon_version,
    )


def _run_add(
    tmp_path: pathlib.Path, entries: dict[str, str | None], *, dry_run: bool = False
) -> tuple[int, pathlib.Path]:
    catalog = []
    for name, min_kanon_version in entries.items():
        xml_path = _write(tmp_path / "repo" / "repo-specs" / f"{name}-marketplace.xml", "<manifest></manifest>\n")
        catalog.append((_metadata(name, min_kanon_version), xml_path, _ENTRY_URL))

    kanon_file = tmp_path / ".kanon"
    args = argparse.Namespace(
        catalog_source=f"{_ENTRY_URL}@main",
        kanon_file=str(kanon_file),
        entries=list(entries),
        force=False,
        dry_run=dry_run,
        alias_override=None,
    )
    with (
        patch(
            "kanon_cli.commands.add._resolve_manifest_repo_for_add",
            return_value=(tmp_path / "repo", _ENTRY_URL, "main"),
        ),
        patch("kanon_cli.commands.add._build_entry_catalog", return_value=catalog),
        patch("kanon_cli.commands.add._resolve_spec", return_value="refs/tags/1.0.0"),
    ):
        return run_add(args), kanon_file


def _declared(kanon_file: pathlib.Path) -> list[str]:
    return [
        line.split("=", 1)[1]
        for line in kanon_file.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"{KANON_MIN_VERSION_KEY}=")
    ]


@pytest.mark.unit
class TestAddWritesCatalogMinimum:
    def test_writes_catalog_minimum_into_new_kanon(self, tmp_path: pathlib.Path) -> None:
        exit_code, kanon_file = _run_add(tmp_path, {"tool-a": "1.2.0"})
        assert exit_code == 0
        assert kanon_file.read_text(encoding="utf-8").startswith(f"{KANON_MIN_VERSION_KEY}=1.2.0\n\n")

    def test_writes_highest_minimum_across_entries(self, tmp_path: pathlib.Path) -> None:
        _, kanon_file = _run_add(tmp_path, {"tool-a": "1.2.0", "tool-b": "2.0.0", "tool-c": None})
        assert _declared(kanon_file) == ["2.0.0"]

    def test_raises_lower_existing_minimum(self, tmp_path: pathlib.Path) -> None:
        _write(tmp_path / ".kanon", f"{KANON_MIN_VERSION_KEY}=1.0.0\n")
        _, kanon_file = _run_add(tmp_path, {"tool-a": "2.0.0"})
        assert _declared(kanon_file) == ["2.0.0"]

    def test_never_lowers_existing_minimum(self, tmp_path: pathlib.Path) -> None:
        _write(tmp_path / ".kanon", f"{KANON_MIN_VERSION_KEY}={__version__}\n")
        _, kanon_file = _run_add(tmp_path, {"tool-a": "1.0.0"})
        assert _declared(kanon_file) == [__version__]

    def test_entry_without_minimum_writes_no_line(self, tmp_path: pathlib.Path) -> None:
        _, kanon_file = _run_add(tmp_path, {"tool-a": None})
        assert _declared(kanon_file) == []

    def test_dry_run_previews_line_without_writing(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path / ".kanon", f"{KANON_MIN_VERSION_KEY}=1.0.0\n")
        _, kanon_file = _run_add(tmp_path, {"tool-a": "2.0.0"}, dry_run=True)
        out = capsys.readouterr().out
        assert f"-{KANON_MIN_VERSION_KEY}=1.0.0" in out
        assert f"+{KANON_MIN_VERSION_KEY}=2.0.0" in out
        assert _declared(kanon_file) == ["1.0.0"]

    def test_entry_needing_newer_kanon_is_refused_before_any_write(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(KanonVersionTooOldError) as exc_info:
            _run_add(tmp_path, {"tool-a": "1.0.0", "tool-b": _NEXT_MAJOR})
        message = str(exc_info.value)
        assert "tool-b" in message
        assert f"requires kanon {_NEXT_MAJOR} or later" in message
        assert not (tmp_path / ".kanon").exists()

    def test_invalid_catalog_minimum_is_refused_before_any_write(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(ValueError, match=KANON_CATALOG_MIN_VERSION_TAG):
            _run_add(tmp_path, {"tool-a": "latest"})
        assert not (tmp_path / ".kanon").exists()
