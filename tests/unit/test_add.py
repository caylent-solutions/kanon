"""Unit tests for kanon_cli.commands.add.

Covers:
- Triple constructor (_build_triple_lines)
- Source-name derivation integration
- Standard-header creation when destination file is absent
- Per-block stdout summary
- Unknown-entry hard error
- Soft-spot rule 1 / rule 3 hard error
- Shell-quoting empty-positional detection
- Argparse subparser structure and flags

AC-TEST-001
"""

import argparse
import io
import pathlib
import textwrap

import pytest

from kanon_cli.core.metadata import CatalogMetadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_metadata(
    name: str = "my-entry",
    url: str = "https://example.com/manifest-repo.git",
    path: str = "repo-specs/my-entry-marketplace.xml",
    version: str = "1.0.0",
) -> CatalogMetadata:
    """Build a minimal CatalogMetadata-like object for use in triple tests."""
    return CatalogMetadata(
        name=name,
        display_name=f"{name} Display",
        description=f"Description of {name}.",
        version=version,
    )


# ---------------------------------------------------------------------------
# Tests for _build_triple_lines
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildTripleLines:
    """Unit tests for the triple-line constructor."""

    def test_returns_three_lines(self) -> None:
        """_build_triple_lines returns exactly three non-empty strings."""
        from kanon_cli.commands.add import _build_triple_lines

        lines = _build_triple_lines(
            source_name="my_entry",
            url="https://example.com/repo.git",
            revision="refs/tags/1.2.0",
            path="repo-specs/my-entry-marketplace.xml",
        )
        assert len(lines) == 3

    def test_url_line_format(self) -> None:
        """URL line is KANON_SOURCE_<source_name>_URL=<url>."""
        from kanon_cli.commands.add import _build_triple_lines

        lines = _build_triple_lines(
            source_name="my_entry",
            url="https://example.com/repo.git",
            revision="refs/tags/1.0.0",
            path="repo-specs/my-entry-marketplace.xml",
        )
        assert lines[0] == "KANON_SOURCE_my_entry_URL=https://example.com/repo.git"

    def test_revision_line_format(self) -> None:
        """REVISION line is KANON_SOURCE_<source_name>_REVISION=<revision>."""
        from kanon_cli.commands.add import _build_triple_lines

        lines = _build_triple_lines(
            source_name="foo_bar",
            url="https://example.com/repo.git",
            revision="refs/tags/2.1.0",
            path="repo-specs/entry-marketplace.xml",
        )
        assert lines[1] == "KANON_SOURCE_foo_bar_REVISION=refs/tags/2.1.0"

    def test_path_line_format(self) -> None:
        """PATH line is KANON_SOURCE_<source_name>_PATH=<path>."""
        from kanon_cli.commands.add import _build_triple_lines

        lines = _build_triple_lines(
            source_name="foo_bar",
            url="https://example.com/repo.git",
            revision="refs/tags/1.0.0",
            path="repo-specs/entry-marketplace.xml",
        )
        assert lines[2] == "KANON_SOURCE_foo_bar_PATH=repo-specs/entry-marketplace.xml"

    def test_source_name_hyphen_converted_to_underscore(self) -> None:
        """Source name uses derive_source_name output -- hyphens are underscores."""
        from kanon_cli.commands.add import _build_triple_lines
        from kanon_cli.core.metadata import derive_source_name

        source_name = derive_source_name("Foo-Bar")
        lines = _build_triple_lines(
            source_name=source_name,
            url="https://example.com/repo.git",
            revision="refs/tags/1.0.0",
            path="repo-specs/foo-bar-marketplace.xml",
        )
        assert "foo_bar" in lines[0]
        assert "foo_bar" in lines[1]
        assert "foo_bar" in lines[2]

    @pytest.mark.parametrize(
        "source_name,url,revision,path",
        [
            (
                "alpha",
                "https://host/alpha.git",
                "refs/tags/1.0.0",
                "repo-specs/alpha-marketplace.xml",
            ),
            (
                "beta_gamma",
                "git@github.com:org/beta.git",
                "refs/tags/0.9.0",
                "repo-specs/sub/beta-marketplace.xml",
            ),
        ],
        ids=["simple-name", "underscore-name-ssh-url"],
    )
    def test_all_three_keys_present(self, source_name: str, url: str, revision: str, path: str) -> None:
        """All three KANON_SOURCE_* keys appear in the output."""
        from kanon_cli.commands.add import _build_triple_lines

        lines = _build_triple_lines(
            source_name=source_name,
            url=url,
            revision=revision,
            path=path,
        )
        joined = "\n".join(lines)
        assert f"KANON_SOURCE_{source_name}_URL" in joined
        assert f"KANON_SOURCE_{source_name}_REVISION" in joined
        assert f"KANON_SOURCE_{source_name}_PATH" in joined


# ---------------------------------------------------------------------------
# Tests for standard-header creation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStandardHeader:
    """Standard-header creation when the destination file is absent."""

    def test_header_written_when_file_absent(self, tmp_path: pathlib.Path) -> None:
        """_write_standard_header creates the file with the three header lines."""
        from kanon_cli.commands.add import _write_standard_header

        dest = tmp_path / ".kanon"
        assert not dest.exists()
        _write_standard_header(dest)
        assert dest.exists()

    def test_header_contains_gitbase(self, tmp_path: pathlib.Path) -> None:
        """Created file contains the GITBASE line."""
        from kanon_cli.commands.add import _write_standard_header

        dest = tmp_path / ".kanon"
        _write_standard_header(dest)
        content = dest.read_text()
        assert "GITBASE=" in content

    def test_header_contains_claude_marketplaces_dir(self, tmp_path: pathlib.Path) -> None:
        """Created file contains the CLAUDE_MARKETPLACES_DIR line."""
        from kanon_cli.commands.add import _write_standard_header

        dest = tmp_path / ".kanon"
        _write_standard_header(dest)
        content = dest.read_text()
        assert "CLAUDE_MARKETPLACES_DIR=" in content

    def test_header_contains_kanon_marketplace_install(self, tmp_path: pathlib.Path) -> None:
        """Created file contains the KANON_MARKETPLACE_INSTALL line."""
        from kanon_cli.commands.add import _write_standard_header

        dest = tmp_path / ".kanon"
        _write_standard_header(dest)
        content = dest.read_text()
        assert "KANON_MARKETPLACE_INSTALL=" in content

    def test_header_values_match_constants(self, tmp_path: pathlib.Path) -> None:
        """Header values come from constants, not inline strings."""
        from kanon_cli.commands.add import _write_standard_header
        from kanon_cli.constants import (
            KANON_HEADER_GITBASE,
            KANON_HEADER_CLAUDE_MARKETPLACES_DIR,
            KANON_HEADER_MARKETPLACE_INSTALL,
        )

        dest = tmp_path / ".kanon"
        _write_standard_header(dest)
        content = dest.read_text()
        assert KANON_HEADER_GITBASE in content
        assert KANON_HEADER_CLAUDE_MARKETPLACES_DIR in content
        assert KANON_HEADER_MARKETPLACE_INSTALL in content

    def test_header_not_written_when_file_exists(self, tmp_path: pathlib.Path) -> None:
        """_write_standard_header does not overwrite an existing file."""
        from kanon_cli.commands.add import _write_standard_header

        dest = tmp_path / ".kanon"
        dest.write_text("EXISTING=value\n")
        _write_standard_header(dest)
        content = dest.read_text()
        assert "EXISTING=value" in content
        # Standard header lines must NOT appear when file already exists
        assert "GITBASE=" not in content


# ---------------------------------------------------------------------------
# Tests for stdout summary line
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStdoutSummary:
    """Per-block stdout summary is printed when a triple block is written."""

    def test_summary_mentions_source_name(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Summary line names the source name."""
        from kanon_cli.commands.add import _append_triple_block

        dest = tmp_path / ".kanon"
        dest.write_text("")
        _append_triple_block(
            dest=dest,
            source_name="my_entry",
            lines=["KANON_SOURCE_my_entry_URL=u", "KANON_SOURCE_my_entry_REVISION=r", "KANON_SOURCE_my_entry_PATH=p"],
        )
        captured = capsys.readouterr()
        assert "my_entry" in captured.out

    def test_summary_mentions_destination_file(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Summary line names the destination file path."""
        from kanon_cli.commands.add import _append_triple_block

        dest = tmp_path / ".kanon"
        dest.write_text("")
        _append_triple_block(
            dest=dest,
            source_name="entry_a",
            lines=["KANON_SOURCE_entry_a_URL=u", "KANON_SOURCE_entry_a_REVISION=r", "KANON_SOURCE_entry_a_PATH=p"],
        )
        captured = capsys.readouterr()
        assert str(dest) in captured.out

    def test_triple_appended_to_file(self, tmp_path: pathlib.Path) -> None:
        """_append_triple_block appends the three lines to the file."""
        from kanon_cli.commands.add import _append_triple_block

        dest = tmp_path / ".kanon"
        dest.write_text("EXISTING=1\n")
        _append_triple_block(
            dest=dest,
            source_name="pkg",
            lines=[
                "KANON_SOURCE_pkg_URL=https://example.com/repo.git",
                "KANON_SOURCE_pkg_REVISION=refs/tags/1.0.0",
                "KANON_SOURCE_pkg_PATH=repo-specs/pkg-marketplace.xml",
            ],
        )
        content = dest.read_text()
        assert "EXISTING=1" in content
        assert "KANON_SOURCE_pkg_URL=https://example.com/repo.git" in content
        assert "KANON_SOURCE_pkg_REVISION=refs/tags/1.0.0" in content
        assert "KANON_SOURCE_pkg_PATH=repo-specs/pkg-marketplace.xml" in content


# ---------------------------------------------------------------------------
# Tests for error paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnknownEntryError:
    """Unknown entry name is a hard error naming the entry."""

    def test_unknown_entry_raises_system_exit(self, tmp_path: pathlib.Path) -> None:
        """run_add exits non-zero when an entry name is not found in the catalog."""
        from kanon_cli.commands.add import _find_entry_by_name

        catalog: list[tuple[CatalogMetadata, pathlib.Path, str]] = []
        with pytest.raises(SystemExit) as exc_info:
            _find_entry_by_name("nonexistent", catalog)
        assert exc_info.value.code != 0

    def test_unknown_entry_names_the_entry_in_stderr(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Error message names the missing entry."""
        from kanon_cli.commands.add import _find_entry_by_name

        catalog: list[tuple[CatalogMetadata, pathlib.Path, str]] = []
        with pytest.raises(SystemExit):
            _find_entry_by_name("missing-pkg", catalog)
        captured = capsys.readouterr()
        assert "missing-pkg" in captured.err

    def test_unknown_entry_suggests_kanon_list(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Error message references 'kanon list' for discovery."""
        from kanon_cli.commands.add import _find_entry_by_name

        catalog: list[tuple[CatalogMetadata, pathlib.Path, str]] = []
        with pytest.raises(SystemExit):
            _find_entry_by_name("missing-pkg", catalog)
        captured = capsys.readouterr()
        assert "kanon list" in captured.err

    def test_known_entry_returned(self, tmp_path: pathlib.Path) -> None:
        """_find_entry_by_name returns the matching entry when found."""
        from kanon_cli.commands.add import _find_entry_by_name

        meta = _make_metadata(name="my-entry")
        xml_path = tmp_path / "my-entry-marketplace.xml"
        xml_path.write_text("")
        catalog = [(meta, xml_path, "https://example.com/repo.git")]
        result_meta, result_path, result_url = _find_entry_by_name("my-entry", catalog)
        assert result_meta.name == "my-entry"
        assert result_path == xml_path
        assert result_url == "https://example.com/repo.git"


@pytest.mark.unit
class TestSoftSpotHardError:
    """Soft-spot rule 1 / rule 3 violations surface as hard errors."""

    def test_parse_error_raises_system_exit(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A CatalogMetadataParseError from the catalog scan exits non-zero."""
        from kanon_cli.commands.add import _build_entry_catalog

        # Create a malformed XML file that _parse_catalog_metadata will reject.
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        bad_xml = repo_specs / "bad-marketplace.xml"
        bad_xml.write_text("NOT VALID XML <<<<<")

        with pytest.raises(SystemExit) as exc_info:
            _build_entry_catalog(tmp_path, url="https://example.com/repo.git")
        assert exc_info.value.code != 0

    def test_parse_error_includes_integrity_wording(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Error message contains spec-canonical 'integrity issues' phrase."""
        from kanon_cli.commands.add import _build_entry_catalog

        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        bad_xml = repo_specs / "bad-marketplace.xml"
        bad_xml.write_text("NOT VALID XML <<<<<")

        with pytest.raises(SystemExit):
            _build_entry_catalog(tmp_path, url="https://example.com/repo.git")
        captured = capsys.readouterr()
        assert "integrity issues" in captured.err

    def test_valid_catalog_returns_entries(self, tmp_path: pathlib.Path) -> None:
        """_build_entry_catalog returns entries for valid XML files."""
        from kanon_cli.commands.add import _build_entry_catalog

        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>entry-a</name>
                <display-name>Entry A</display-name>
                <description>Test entry.</description>
                <version>1.0.0</version>
                <type>plugin</type>
                <owner-name>Owner</owner-name>
                <owner-email>owner@example.com</owner-email>
                <keywords>test</keywords>
              </catalog-metadata>
            </manifest>
        """)
        xml_file = repo_specs / "entry-a-marketplace.xml"
        xml_file.write_text(xml_content)

        catalog = _build_entry_catalog(tmp_path, url="https://example.com/repo.git")
        assert len(catalog) == 1
        assert catalog[0][0].name == "entry-a"


# ---------------------------------------------------------------------------
# Tests for argparse subparser structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddSubparser:
    """Tests for the argparse subparser registered by the add command."""

    def _get_add_parser(self) -> argparse.ArgumentParser:
        """Build the top-level parser and extract the 'add' sub-parser."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                choices = action.choices
                assert "add" in choices, "add subcommand not registered in top-level parser"
                return choices["add"]
        raise AssertionError("No subparsers found in build_parser()")

    def test_add_subcommand_registered(self) -> None:
        """build_parser() includes 'add' as a registered subcommand."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "https://example.com/repo.git@main"])
        assert args.command == "add"

    def test_add_subcommand_has_catalog_source_flag(self) -> None:
        """The 'add' subcommand accepts --catalog-source."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "https://example.com/repo.git@main"])
        assert args.catalog_source == "https://example.com/repo.git@main"

    def test_add_subcommand_has_kanon_file_flag(self) -> None:
        """The 'add' subcommand accepts --kanon-file."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "x@main", "--kanon-file", "/tmp/.kanon"])
        assert args.kanon_file == "/tmp/.kanon"

    def test_kanon_file_default_is_dotkanon(self) -> None:
        """--kanon-file defaults to ./.kanon when not supplied."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "x@main"])
        assert args.kanon_file == "./.kanon"

    def test_add_subcommand_has_no_color_flag(self) -> None:
        """The 'add' subcommand propagates --no-color from the root parser."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["--no-color", "add", "entry-a", "--catalog-source", "x@main"])
        assert args.no_color is True

    def test_add_subcommand_positional_accepts_multiple(self) -> None:
        """The 'add' subcommand accepts one or more positional <name>[@<spec>] entries."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "entry-b", "--catalog-source", "x@main"])
        assert "entry-a" in args.entries
        assert "entry-b" in args.entries

    def test_add_subcommand_sets_run_add_as_func(self) -> None:
        """The 'add' subcommand sets args.func to run_add."""
        from kanon_cli.cli import build_parser
        from kanon_cli.commands.add import run_add

        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "x@main"])
        assert args.func is run_add

    def test_add_help_exits_0(self) -> None:
        """kanon add --help exits 0."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["add", "--help"])
        assert exc_info.value.code == 0

    def test_add_short_dash_h_exits_0(self) -> None:
        """kanon add -h exits 0 (add_help=True on the add subparser)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["add", "-h"])
        assert exc_info.value.code == 0

    def test_add_subparser_has_add_help_true(self) -> None:
        """The 'add' subparser has add_help=True set explicitly."""
        add_parser = self._get_add_parser()
        assert add_parser.add_help is True, "add subparser must have add_help=True so '-h' is accepted"

    def test_add_help_mentions_kanon_file(self, capsys: pytest.CaptureFixture[str]) -> None:
        """kanon add --help text mentions --kanon-file and its env var."""
        add_parser = self._get_add_parser()
        buf = io.StringIO()
        add_parser.print_help(file=buf)
        help_text = buf.getvalue()
        assert "--kanon-file" in help_text
        assert "KANON_KANON_FILE" in help_text

    def test_add_help_mentions_spec_grammar(self, capsys: pytest.CaptureFixture[str]) -> None:
        """kanon add --help text references the @<spec> grammar."""
        add_parser = self._get_add_parser()
        buf = io.StringIO()
        add_parser.print_help(file=buf)
        help_text = buf.getvalue()
        assert "@" in help_text


# ---------------------------------------------------------------------------
# Tests for spec-split on last '@'
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSplitNameSpec:
    """_split_name_spec splits on the LAST '@' (spec Section 4.0)."""

    @pytest.mark.parametrize(
        "raw,expected_name,expected_spec",
        [
            ("entry-a", "entry-a", None),
            ("entry-a@==1.0.0", "entry-a", "==1.0.0"),
            ("git@github.com:org/entry@>=1.0.0", "git@github.com:org/entry", ">=1.0.0"),
            ("entry@~=1.2", "entry", "~=1.2"),
        ],
        ids=["no-spec", "eq-spec", "ssh-url-entry", "compatible-spec"],
    )
    def test_split_name_spec(self, raw: str, expected_name: str, expected_spec: str | None) -> None:
        """_split_name_spec splits on the last @ character."""
        from kanon_cli.commands.add import _split_name_spec

        name, spec = _split_name_spec(raw)
        assert name == expected_name
        assert spec == expected_spec


# ---------------------------------------------------------------------------
# Tests for KANON_KANON_FILE_ENV and KANON_HEADER_* constants
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddConstants:
    """Constants required by the add command exist in kanon_cli.constants."""

    def test_kanon_kanon_file_env_exists(self) -> None:
        """KANON_KANON_FILE_ENV constant exists in constants module."""
        from kanon_cli.constants import KANON_KANON_FILE_ENV

        assert isinstance(KANON_KANON_FILE_ENV, str)
        assert KANON_KANON_FILE_ENV == "KANON_KANON_FILE"

    def test_kanon_header_gitbase_exists(self) -> None:
        """KANON_HEADER_GITBASE constant exists in constants module."""
        from kanon_cli.constants import KANON_HEADER_GITBASE

        assert isinstance(KANON_HEADER_GITBASE, str)
        assert len(KANON_HEADER_GITBASE) > 0

    def test_kanon_header_claude_marketplaces_dir_exists(self) -> None:
        """KANON_HEADER_CLAUDE_MARKETPLACES_DIR constant exists in constants module."""
        from kanon_cli.constants import KANON_HEADER_CLAUDE_MARKETPLACES_DIR

        assert isinstance(KANON_HEADER_CLAUDE_MARKETPLACES_DIR, str)
        assert len(KANON_HEADER_CLAUDE_MARKETPLACES_DIR) > 0

    def test_kanon_header_marketplace_install_exists(self) -> None:
        """KANON_HEADER_MARKETPLACE_INSTALL constant exists in constants module."""
        from kanon_cli.constants import KANON_HEADER_MARKETPLACE_INSTALL

        assert isinstance(KANON_HEADER_MARKETPLACE_INSTALL, str)
        assert len(KANON_HEADER_MARKETPLACE_INSTALL) > 0

    def test_header_gitbase_value_matches_template(self) -> None:
        """KANON_HEADER_GITBASE matches the .kanon template content."""
        from kanon_cli.constants import KANON_HEADER_GITBASE

        assert "<YOUR_GIT_ORG_BASE_URL>" in KANON_HEADER_GITBASE

    def test_header_claude_marketplaces_dir_value(self) -> None:
        """KANON_HEADER_CLAUDE_MARKETPLACES_DIR matches the .kanon template."""
        from kanon_cli.constants import KANON_HEADER_CLAUDE_MARKETPLACES_DIR

        assert "${HOME}/.claude-marketplaces" in KANON_HEADER_CLAUDE_MARKETPLACES_DIR

    def test_header_marketplace_install_value(self) -> None:
        """KANON_HEADER_MARKETPLACE_INSTALL contains the template placeholder."""
        from kanon_cli.constants import KANON_HEADER_MARKETPLACE_INSTALL

        assert "<true|false>" in KANON_HEADER_MARKETPLACE_INSTALL


# ---------------------------------------------------------------------------
# Tests for _resolve_spec
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveSpec:
    """_resolve_spec resolves version spec against manifest repo tags."""

    def test_no_spec_returns_highest_tag_from_fake_tags(self) -> None:
        """When spec is None, highest PEP 440 tag is returned from mocked _list_tags."""
        from unittest.mock import patch

        from kanon_cli.commands.add import _resolve_spec

        fake_tags = ["refs/tags/1.0.0", "refs/tags/1.1.0", "refs/tags/1.2.0"]
        with patch("kanon_cli.commands.add._list_tags", return_value=fake_tags):
            result = _resolve_spec("https://example.com/repo.git", None)
        assert result == "refs/tags/1.2.0"

    def test_no_spec_with_empty_tags_exits_nonzero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When spec is None and _list_tags returns empty list, exits non-zero."""
        from unittest.mock import patch

        from kanon_cli.commands.add import _resolve_spec

        with patch("kanon_cli.commands.add._list_tags", return_value=[]):
            with pytest.raises(SystemExit) as exc_info:
                _resolve_spec("https://example.com/repo.git", None)
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "manifest repo has no PEP 440-valid tags" in captured.err

    def test_explicit_spec_delegates_to_resolve_version(self) -> None:
        """When spec is given, resolve_version() is called and result is returned."""
        from unittest.mock import patch

        from kanon_cli.commands.add import _resolve_spec

        with patch(
            "kanon_cli.commands.add.resolve_version",
            return_value="refs/tags/1.0.0",
        ) as mock_rv:
            result = _resolve_spec("https://example.com/repo.git", "==1.0.0")
        mock_rv.assert_called_once_with("https://example.com/repo.git", "==1.0.0")
        assert result == "refs/tags/1.0.0"


# ---------------------------------------------------------------------------
# Tests for _xml_repo_relative_path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestXmlRepoRelativePath:
    """_xml_repo_relative_path returns the repo-relative path string."""

    def test_relative_path_returned(self, tmp_path: pathlib.Path) -> None:
        """Returns the path of xml_path relative to manifest_root."""
        from kanon_cli.commands.add import _xml_repo_relative_path

        manifest_root = tmp_path / "repo"
        manifest_root.mkdir()
        xml_path = manifest_root / "repo-specs" / "foo-marketplace.xml"
        result = _xml_repo_relative_path(manifest_root, xml_path)
        assert result == "repo-specs/foo-marketplace.xml"

    def test_nested_path_returned(self, tmp_path: pathlib.Path) -> None:
        """Returns the correct path for nested XML files."""
        from kanon_cli.commands.add import _xml_repo_relative_path

        manifest_root = tmp_path / "repo"
        manifest_root.mkdir()
        xml_path = manifest_root / "repo-specs" / "sub" / "bar-marketplace.xml"
        result = _xml_repo_relative_path(manifest_root, xml_path)
        assert result == "repo-specs/sub/bar-marketplace.xml"


# ---------------------------------------------------------------------------
# Tests for _resolve_manifest_repo_for_add error paths (unit-level)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveManifestRepoForAdd:
    """_resolve_manifest_repo_for_add error paths."""

    def test_invalid_catalog_source_exits_nonzero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """An invalid catalog source string (no '@') exits non-zero."""
        from kanon_cli.commands.add import _resolve_manifest_repo_for_add

        with pytest.raises(SystemExit) as exc_info:
            _resolve_manifest_repo_for_add("not-a-valid-source")
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err

    def test_git_clone_failure_exits_nonzero(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A failed git clone exits non-zero with an error message."""
        from kanon_cli.commands.add import _resolve_manifest_repo_for_add

        with pytest.raises(SystemExit) as exc_info:
            _resolve_manifest_repo_for_add("file:///does/not/exist.git@main")
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err


# ---------------------------------------------------------------------------
# Tests for run_add entry point (unit-level, mocked)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunAddMissingCatalogSource:
    """run_add exits non-zero when no catalog source is configured."""

    def test_missing_catalog_source_exits_nonzero(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_add exits non-zero when catalog_source is None and env var is absent."""
        import argparse

        from kanon_cli.commands.add import run_add

        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        args = argparse.Namespace(
            catalog_source=None,
            kanon_file="./.kanon",
            entries=["entry-a"],
            force=False,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc_info:
            run_add(args)
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "catalog source" in captured.err.lower() or "ERROR" in captured.err


@pytest.mark.unit
class TestBuildEntryCatalogNoRepoSpecs:
    """_build_entry_catalog returns empty list when repo-specs dir is absent."""

    def test_no_repo_specs_dir_returns_empty(self, tmp_path: pathlib.Path) -> None:
        """Returns empty list when the manifest root has no repo-specs directory."""
        from kanon_cli.commands.add import _build_entry_catalog

        result = _build_entry_catalog(tmp_path, url="https://example.com/repo.git")
        assert result == []


@pytest.mark.unit
class TestResolveManifestRepoForAddVersionConstraint:
    """_resolve_manifest_repo_for_add handles version-constrained refs."""

    def test_latest_ref_resolved_to_star(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A 'latest' ref is converted to '*' and passed through resolve_version."""
        from unittest.mock import patch

        from kanon_cli.commands.add import _resolve_manifest_repo_for_add

        fake_resolved = "refs/tags/2.0.0"
        fake_repo_dir = tmp_path / "repo"
        fake_repo_dir.mkdir()

        with (
            patch("kanon_cli.commands.add.resolve_version", return_value=fake_resolved),
            patch(
                "kanon_cli.commands.add.subprocess.run",
                return_value=type("R", (), {"returncode": 0, "stderr": ""})(),
            ),
            patch(
                "kanon_cli.commands.add.tempfile.mkdtemp",
                return_value=str(tmp_path / "clone"),
            ),
        ):
            (tmp_path / "clone").mkdir(exist_ok=True)
            repo_dir, url, resolved_ref = _resolve_manifest_repo_for_add("https://example.com/repo.git@latest")
        assert resolved_ref == "2.0.0"

    def test_version_constraint_ref_is_resolved(self, tmp_path: pathlib.Path) -> None:
        """A version-constraint ref like '>=1.0.0' is resolved via resolve_version."""
        from unittest.mock import patch

        from kanon_cli.commands.add import _resolve_manifest_repo_for_add

        fake_resolved = "refs/tags/1.5.0"
        with (
            patch("kanon_cli.commands.add.resolve_version", return_value=fake_resolved),
            patch(
                "kanon_cli.commands.add.subprocess.run",
                return_value=type("R", (), {"returncode": 0, "stderr": ""})(),
            ),
            patch(
                "kanon_cli.commands.add.tempfile.mkdtemp",
                return_value=str(tmp_path / "clone"),
            ),
        ):
            (tmp_path / "clone").mkdir(exist_ok=True)
            _repo_dir, url, resolved_ref = _resolve_manifest_repo_for_add("https://example.com/repo.git@>=1.0.0")
        assert resolved_ref == "1.5.0"
        assert url == "https://example.com/repo.git"


@pytest.mark.unit
class TestRunAddHappyPath:
    """run_add happy path via mocked sub-functions."""

    def test_run_add_success_returns_0(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """run_add returns 0 when all sub-functions succeed."""
        import argparse
        import textwrap

        from unittest.mock import patch

        from kanon_cli.commands.add import run_add

        kanon_file = tmp_path / ".kanon"

        # Create a minimal metadata for use in catalog
        meta = CatalogMetadata(
            name="entry-a",
            display_name="Entry A",
            description="Test entry.",
            version="1.0.0",
        )
        xml_path = tmp_path / "repo" / "repo-specs" / "entry-a-marketplace.xml"
        xml_path.parent.mkdir(parents=True)
        xml_path.write_text(
            textwrap.dedent("""\
                <?xml version="1.0" encoding="UTF-8"?>
                <manifest>
                  <catalog-metadata>
                    <name>entry-a</name>
                    <display-name>Entry A</display-name>
                    <description>Test.</description>
                    <version>1.0.0</version>
                    <type>plugin</type>
                    <owner-name>Owner</owner-name>
                    <owner-email>o@example.com</owner-email>
                    <keywords>test</keywords>
                  </catalog-metadata>
                </manifest>
            """)
        )
        manifest_root = tmp_path / "repo"

        args = argparse.Namespace(
            catalog_source="https://example.com/repo.git@main",
            kanon_file=str(kanon_file),
            entries=["entry-a"],
            force=False,
            dry_run=False,
        )

        with (
            patch(
                "kanon_cli.commands.add._resolve_manifest_repo_for_add",
                return_value=(manifest_root, "https://example.com/repo.git", "main"),
            ),
            patch(
                "kanon_cli.commands.add._build_entry_catalog",
                return_value=[(meta, xml_path, "https://example.com/repo.git")],
            ),
            patch(
                "kanon_cli.commands.add._resolve_spec",
                return_value="refs/tags/1.0.0",
            ),
        ):
            result = run_add(args)

        assert result == 0
        assert kanon_file.exists()
        content = kanon_file.read_text()
        assert "KANON_SOURCE_entry_a_URL=" in content
        assert "KANON_SOURCE_entry_a_REVISION=refs/tags/1.0.0" in content
        assert "KANON_SOURCE_entry_a_PATH=" in content


# ---------------------------------------------------------------------------
# Tests for workspace lock integration in run_add
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunAddWorkspaceLock:
    """run_add wraps the .kanon write inside kanon_workspace_lock (AC-FUNC-005)."""

    def test_run_add_creates_kanon_data_dir(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """run_add creates .kanon-data/ as part of workspace lock acquisition.

        The kanon_workspace_lock context manager creates .kanon-data/ eagerly;
        this test confirms that a normal run_add call in a fresh workspace
        (with no pre-existing .kanon-data/) creates the directory.

        Args:
            tmp_path: Pytest-provided temporary directory.
            capsys: Pytest stdout/stderr capture fixture.
        """
        import textwrap
        from unittest.mock import patch

        from kanon_cli.commands.add import run_add

        kanon_file = tmp_path / ".kanon"
        meta = CatalogMetadata(
            name="entry-b",
            display_name="Entry B",
            description="Test.",
            version="1.0.0",
        )
        xml_path = tmp_path / "repo" / "repo-specs" / "entry-b-marketplace.xml"
        xml_path.parent.mkdir(parents=True)
        xml_path.write_text(
            textwrap.dedent("""\
                <?xml version="1.0" encoding="UTF-8"?>
                <manifest>
                  <catalog-metadata>
                    <name>entry-b</name>
                    <display-name>Entry B</display-name>
                    <description>Test.</description>
                    <version>1.0.0</version>
                    <type>plugin</type>
                    <owner-name>Owner</owner-name>
                    <owner-email>o@example.com</owner-email>
                    <keywords>test</keywords>
                  </catalog-metadata>
                </manifest>
            """)
        )
        manifest_root = tmp_path / "repo"

        args = argparse.Namespace(
            catalog_source="https://example.com/repo.git@main",
            kanon_file=str(kanon_file),
            entries=["entry-b"],
            force=False,
            dry_run=False,
        )

        # Pre-condition: .kanon-data/ must not exist.
        assert not (tmp_path / ".kanon-data").exists()

        with (
            patch(
                "kanon_cli.commands.add._resolve_manifest_repo_for_add",
                return_value=(manifest_root, "https://example.com/repo.git", "main"),
            ),
            patch(
                "kanon_cli.commands.add._build_entry_catalog",
                return_value=[(meta, xml_path, "https://example.com/repo.git")],
            ),
            patch(
                "kanon_cli.commands.add._resolve_spec",
                return_value="refs/tags/1.0.0",
            ),
        ):
            run_add(args)

        assert (tmp_path / ".kanon-data").is_dir(), (
            "run_add must create .kanon-data/ via kanon_workspace_lock eager-create "
            "when the workspace has no prior .kanon-data/ directory"
        )

    def test_run_add_dry_run_does_not_create_kanon_data_dir(self, tmp_path: pathlib.Path) -> None:
        """run_add --dry-run does not acquire the workspace lock and does not create .kanon-data/.

        The lock is only acquired on the non-dry-run write path. Dry runs only
        read the existing .kanon file (or check for collisions) and print diffs
        without any on-disk changes.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        import textwrap
        from unittest.mock import patch

        from kanon_cli.commands.add import run_add

        kanon_file = tmp_path / ".kanon"
        meta = CatalogMetadata(
            name="entry-c",
            display_name="Entry C",
            description="Test.",
            version="1.0.0",
        )
        xml_path = tmp_path / "repo" / "repo-specs" / "entry-c-marketplace.xml"
        xml_path.parent.mkdir(parents=True)
        xml_path.write_text(
            textwrap.dedent("""\
                <?xml version="1.0" encoding="UTF-8"?>
                <manifest>
                  <catalog-metadata>
                    <name>entry-c</name>
                    <display-name>Entry C</display-name>
                    <description>Test.</description>
                    <version>1.0.0</version>
                    <type>plugin</type>
                    <owner-name>Owner</owner-name>
                    <owner-email>o@example.com</owner-email>
                    <keywords>test</keywords>
                  </catalog-metadata>
                </manifest>
            """)
        )
        manifest_root = tmp_path / "repo"

        args = argparse.Namespace(
            catalog_source="https://example.com/repo.git@main",
            kanon_file=str(kanon_file),
            entries=["entry-c"],
            force=False,
            dry_run=True,
        )

        with (
            patch(
                "kanon_cli.commands.add._resolve_manifest_repo_for_add",
                return_value=(manifest_root, "https://example.com/repo.git", "main"),
            ),
            patch(
                "kanon_cli.commands.add._build_entry_catalog",
                return_value=[(meta, xml_path, "https://example.com/repo.git")],
            ),
            patch(
                "kanon_cli.commands.add._resolve_spec",
                return_value="refs/tags/1.0.0",
            ),
        ):
            result = run_add(args)

        assert result == 0
        # Dry run must not create .kanon-data/ -- the lock is not acquired.
        assert not (tmp_path / ".kanon-data").exists(), (
            "run_add --dry-run must not create .kanon-data/; "
            "the workspace lock is only acquired on the non-dry-run write path"
        )
