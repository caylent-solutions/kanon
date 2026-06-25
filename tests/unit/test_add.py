"""Unit tests for kanon_cli.commands.add.

Covers:
- Alias-keyed block constructor (_build_source_block_lines)
- Source-name (alias) derivation integration
- No standard-header is written (spec Section 5.1): per-dependency blocks only
- Per-block stdout summary
- Unknown-entry hard error
- Soft-spot rule 1 / rule 3 hard error
- Shell-quoting empty-positional detection
- Argparse subparser structure and flags
- utf-8 encoding sweep (AC-12): read_text/write_text callsites specify encoding="utf-8"

AC-TEST-001
"""

import argparse
import io
import pathlib
import textwrap

import pytest

from kanon_cli.core.metadata import CatalogMetadata
from tests.conftest import bare_text_io_calls


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


@pytest.mark.unit
class TestBuildSourceBlockLines:
    """Unit tests for the alias-keyed block-line constructor."""

    def test_returns_five_lines_when_not_marketplace(self) -> None:
        """_build_source_block_lines returns exactly five strings when marketplace
        is False (no _MARKETPLACE line is appended).
        """
        from kanon_cli.commands.add import _build_source_block_lines

        lines = _build_source_block_lines(
            source_name="my_entry",
            url="https://example.com/repo.git",
            ref="refs/tags/1.2.0",
            path="repo-specs/my-entry-marketplace.xml",
            name="my-entry",
            gitbase="https://example.com",
            marketplace=False,
        )
        assert len(lines) == 5
        joined = "\n".join(lines)
        assert "_MARKETPLACE" not in joined

    def test_marketplace_true_appends_marketplace_line(self) -> None:
        """marketplace=True appends a sixth line: KANON_SOURCE_<alias>_MARKETPLACE=true."""
        from kanon_cli.commands.add import _build_source_block_lines

        lines = _build_source_block_lines(
            source_name="my_entry",
            url="https://example.com/repo.git",
            ref="refs/tags/1.2.0",
            path="repo-specs/my-entry-marketplace.xml",
            name="my-entry",
            gitbase="https://example.com",
            marketplace=True,
        )
        assert len(lines) == 6
        assert lines[5] == "KANON_SOURCE_my_entry_MARKETPLACE=true"

    def test_marketplace_false_omits_marketplace_line(self) -> None:
        """marketplace=False never emits a _MARKETPLACE line (absence == false)."""
        from kanon_cli.commands.add import _build_source_block_lines

        lines = _build_source_block_lines(
            source_name="my_entry",
            url="https://example.com/repo.git",
            ref="refs/tags/1.2.0",
            path="repo-specs/my-entry-marketplace.xml",
            name="my-entry",
            gitbase="https://example.com",
            marketplace=False,
        )

        assert not any(line.endswith("_MARKETPLACE=false") for line in lines)
        assert not any("_MARKETPLACE" in line for line in lines)

    def test_url_line_format(self) -> None:
        """URL line is KANON_SOURCE_<alias>_URL=<url>."""
        from kanon_cli.commands.add import _build_source_block_lines

        lines = _build_source_block_lines(
            source_name="my_entry",
            url="https://example.com/repo.git",
            ref="refs/tags/1.0.0",
            path="repo-specs/my-entry-marketplace.xml",
            name="my-entry",
            gitbase="https://example.com",
            marketplace=False,
        )
        assert lines[0] == "KANON_SOURCE_my_entry_URL=https://example.com/repo.git"

    def test_ref_line_format(self) -> None:
        """REF line is KANON_SOURCE_<alias>_REF=<ref> (no _REVISION)."""
        from kanon_cli.commands.add import _build_source_block_lines

        lines = _build_source_block_lines(
            source_name="foo_bar",
            url="https://example.com/repo.git",
            ref="refs/tags/2.1.0",
            path="repo-specs/entry-marketplace.xml",
            name="foo-bar",
            gitbase="https://example.com",
            marketplace=False,
        )
        assert lines[1] == "KANON_SOURCE_foo_bar_REF=refs/tags/2.1.0"

    def test_path_line_format(self) -> None:
        """PATH line is KANON_SOURCE_<alias>_PATH=<path>."""
        from kanon_cli.commands.add import _build_source_block_lines

        lines = _build_source_block_lines(
            source_name="foo_bar",
            url="https://example.com/repo.git",
            ref="refs/tags/1.0.0",
            path="repo-specs/entry-marketplace.xml",
            name="foo-bar",
            gitbase="https://example.com",
            marketplace=False,
        )
        assert lines[2] == "KANON_SOURCE_foo_bar_PATH=repo-specs/entry-marketplace.xml"

    def test_name_line_format(self) -> None:
        """NAME line is KANON_SOURCE_<alias>_NAME=<original manifest name>."""
        from kanon_cli.commands.add import _build_source_block_lines

        lines = _build_source_block_lines(
            source_name="foo_bar",
            url="https://example.com/repo.git",
            ref="refs/tags/1.0.0",
            path="repo-specs/entry-marketplace.xml",
            name="Foo-Bar",
            gitbase="https://example.com",
            marketplace=False,
        )
        assert lines[3] == "KANON_SOURCE_foo_bar_NAME=Foo-Bar"

    def test_gitbase_line_format(self) -> None:
        """GITBASE line is KANON_SOURCE_<alias>_GITBASE=<org base>."""
        from kanon_cli.commands.add import _build_source_block_lines

        lines = _build_source_block_lines(
            source_name="foo_bar",
            url="https://example.com/org/repo.git",
            ref="refs/tags/1.0.0",
            path="repo-specs/entry-marketplace.xml",
            name="foo-bar",
            gitbase="https://example.com/org",
            marketplace=False,
        )
        assert lines[4] == "KANON_SOURCE_foo_bar_GITBASE=https://example.com/org"

    def test_no_revision_key_emitted(self) -> None:
        """The block never emits a _REVISION key (renamed to _REF)."""
        from kanon_cli.commands.add import _build_source_block_lines

        lines = _build_source_block_lines(
            source_name="my_entry",
            url="https://example.com/repo.git",
            ref="refs/tags/1.0.0",
            path="repo-specs/my-entry-marketplace.xml",
            name="my-entry",
            gitbase="https://example.com",
            marketplace=False,
        )
        joined = "\n".join(lines)
        assert "_REVISION" not in joined

    def test_source_name_hyphen_converted_to_underscore(self) -> None:
        """Alias uses derive_source_name output -- hyphens become underscores."""
        from kanon_cli.commands.add import _build_source_block_lines
        from kanon_cli.core.metadata import derive_source_name

        source_name = derive_source_name("Foo-Bar")
        lines = _build_source_block_lines(
            source_name=source_name,
            url="https://example.com/repo.git",
            ref="refs/tags/1.0.0",
            path="repo-specs/foo-bar-marketplace.xml",
            name="Foo-Bar",
            gitbase="https://example.com",
            marketplace=False,
        )
        for line in lines:
            assert "foo_bar" in line

    @pytest.mark.parametrize(
        "source_name,url,ref,path",
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
    def test_all_five_keys_present(self, source_name: str, url: str, ref: str, path: str) -> None:
        """All five KANON_SOURCE_* keys appear in the output."""
        from kanon_cli.commands.add import _build_source_block_lines

        lines = _build_source_block_lines(
            source_name=source_name,
            url=url,
            ref=ref,
            path=path,
            name=source_name,
            gitbase="https://example.com",
            marketplace=False,
        )
        joined = "\n".join(lines)
        assert f"KANON_SOURCE_{source_name}_URL" in joined
        assert f"KANON_SOURCE_{source_name}_REF" in joined
        assert f"KANON_SOURCE_{source_name}_PATH" in joined
        assert f"KANON_SOURCE_{source_name}_NAME" in joined
        assert f"KANON_SOURCE_{source_name}_GITBASE" in joined


@pytest.mark.unit
class TestNoStandardHeader:
    """add writes no standard header: the _write_standard_header writer is removed."""

    def test_write_standard_header_is_removed(self) -> None:
        """The _write_standard_header writer no longer exists in the add module."""
        import kanon_cli.commands.add as add_module

        assert not hasattr(add_module, "_write_standard_header"), (
            "_write_standard_header must be removed (spec Section 5.1 / DoD): "
            "per-dependency blocks fully replace the global header."
        )

    def test_fresh_file_has_no_header_or_catalog_block(self, tmp_path: pathlib.Path) -> None:
        """A fresh .kanon written by add carries only the per-dep block, no header.

        No global [catalog] block, no KANON_MARKETPLACE_INSTALL header line, and
        no bare GITBASE= header line (the org base lives in the per-dep
        KANON_SOURCE_<alias>_GITBASE field).
        """
        import argparse
        import textwrap
        from unittest.mock import patch

        from kanon_cli.commands.add import run_add

        kanon_file = tmp_path / ".kanon"
        meta = CatalogMetadata(
            name="entry-a",
            display_name="Entry A",
            description="Test.",
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
            catalog_source="https://example.com/org/repo.git@main",
            kanon_file=str(kanon_file),
            entries=["entry-a"],
            force=False,
            dry_run=False,
        )
        with (
            patch(
                "kanon_cli.commands.add._resolve_manifest_repo_for_add",
                return_value=(manifest_root, "https://example.com/org/repo.git", "main"),
            ),
            patch(
                "kanon_cli.commands.add._build_entry_catalog",
                return_value=[(meta, xml_path, "https://example.com/org/repo.git")],
            ),
            patch(
                "kanon_cli.commands.add._resolve_spec",
                return_value="refs/tags/1.0.0",
            ),
        ):
            assert run_add(args) == 0

        content = kanon_file.read_text()
        assert "[catalog]" not in content
        assert "KANON_MARKETPLACE_INSTALL" not in content

        for line in content.splitlines():
            assert not line.startswith("GITBASE="), f"unexpected GITBASE header line: {line!r}"
        assert "KANON_SOURCE_entry_a_GITBASE=https://example.com/org" in content


@pytest.mark.unit
class TestStdoutSummary:
    """Per-block stdout summary is printed when a source block is written."""

    def test_summary_mentions_source_name(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Summary line names the source alias."""
        from kanon_cli.commands.add import _append_source_block

        dest = tmp_path / ".kanon"
        dest.write_text("")
        _append_source_block(
            dest=dest,
            source_name="my_entry",
            lines=[
                "KANON_SOURCE_my_entry_URL=u",
                "KANON_SOURCE_my_entry_REF=r",
                "KANON_SOURCE_my_entry_PATH=p",
                "KANON_SOURCE_my_entry_NAME=my-entry",
                "KANON_SOURCE_my_entry_GITBASE=https://example.com",
            ],
        )
        captured = capsys.readouterr()
        assert "my_entry" in captured.out

    def test_summary_mentions_destination_file(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Summary line names the destination file path."""
        from kanon_cli.commands.add import _append_source_block

        dest = tmp_path / ".kanon"
        dest.write_text("")
        _append_source_block(
            dest=dest,
            source_name="entry_a",
            lines=[
                "KANON_SOURCE_entry_a_URL=u",
                "KANON_SOURCE_entry_a_REF=r",
                "KANON_SOURCE_entry_a_PATH=p",
                "KANON_SOURCE_entry_a_NAME=entry-a",
                "KANON_SOURCE_entry_a_GITBASE=https://example.com",
            ],
        )
        captured = capsys.readouterr()
        assert str(dest) in captured.out

    def test_block_appended_to_file(self, tmp_path: pathlib.Path) -> None:
        """_append_source_block appends the block lines to the file."""
        from kanon_cli.commands.add import _append_source_block

        dest = tmp_path / ".kanon"
        dest.write_text("EXISTING=1\n")
        _append_source_block(
            dest=dest,
            source_name="pkg",
            lines=[
                "KANON_SOURCE_pkg_URL=https://example.com/repo.git",
                "KANON_SOURCE_pkg_REF=refs/tags/1.0.0",
                "KANON_SOURCE_pkg_PATH=repo-specs/pkg-marketplace.xml",
                "KANON_SOURCE_pkg_NAME=pkg",
                "KANON_SOURCE_pkg_GITBASE=https://example.com",
            ],
        )
        content = dest.read_text()
        assert "EXISTING=1" in content
        assert "KANON_SOURCE_pkg_URL=https://example.com/repo.git" in content
        assert "KANON_SOURCE_pkg_REF=refs/tags/1.0.0" in content
        assert "KANON_SOURCE_pkg_PATH=repo-specs/pkg-marketplace.xml" in content
        assert "KANON_SOURCE_pkg_NAME=pkg" in content
        assert "KANON_SOURCE_pkg_GITBASE=https://example.com" in content

    def test_append_to_empty_file_has_no_leading_blank_line(self, tmp_path: pathlib.Path) -> None:
        """Appending to a fresh/empty .kanon does not start with a blank line."""
        from kanon_cli.commands.add import _append_source_block

        dest = tmp_path / ".kanon"
        _append_source_block(
            dest=dest,
            source_name="pkg",
            lines=["KANON_SOURCE_pkg_URL=u"],
        )
        content = dest.read_text()
        assert not content.startswith("\n")
        assert content.splitlines()[0] == "KANON_SOURCE_pkg_URL=u"


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
        """Error message references 'kanon search' for discovery."""
        from kanon_cli.commands.add import _find_entry_by_name

        catalog: list[tuple[CatalogMetadata, pathlib.Path, str]] = []
        with pytest.raises(SystemExit):
            _find_entry_by_name("missing-pkg", catalog)
        captured = capsys.readouterr()
        assert "kanon search" in captured.err

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

        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        bad_xml = repo_specs / "bad-marketplace.xml"
        bad_xml.write_text("<catalog-metadata>NOT VALID XML <<<<<")

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
        bad_xml.write_text("<catalog-metadata>NOT VALID XML <<<<<")

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

    @pytest.mark.parametrize(
        "expected_substring",
        [
            "Note: when supplying a PEP 440 range, quote the spec to avoid shell parsing:",
            "kanon add 'package-a@>=1.0,<2.0'",
        ],
        ids=["quoting-reminder-note", "quoting-reminder-example"],
    )
    def test_add_help_contains_quoting_reminder(self, expected_substring: str) -> None:
        """kanon add --help text contains the spec sec4.7 shell-quoting reminder.

        AC-FUNC-001 requires the quoting-reminder note text.
        AC-FUNC-002 requires the worked example with a range operator.
        AC-TEST-002 requires this assertion to be parametrized so it can
        actually fail if the reminder is removed.
        """
        add_parser = self._get_add_parser()
        buf = io.StringIO()
        add_parser.print_help(file=buf)
        help_text = buf.getvalue()
        assert expected_substring in help_text, (
            f"kanon add --help is missing required quoting-reminder text.\n"
            f"Expected substring: {expected_substring!r}\n"
            f"Actual help text:\n{help_text}"
        )


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


@pytest.mark.unit
class TestDeriveGitbaseFromCatalogSource:
    """_derive_gitbase_from_catalog_source extracts scheme + authority from catalog URLs."""

    @pytest.mark.parametrize(
        "url,expected_gitbase",
        [
            (
                "https://github.com/my-org/my-repo.git",
                "https://github.com/my-org",
            ),
            (
                "https://github.com/my-org/my-repo",
                "https://github.com/my-org",
            ),
            (
                "http://internal.example.com/team/repo.git",
                "http://internal.example.com/team",
            ),
            (
                "ssh://git@github.com/caylent/kanon.git",
                "ssh://git@github.com/caylent",
            ),
            (
                "ssh://git@github.com/caylent/kanon",
                "ssh://git@github.com/caylent",
            ),
            (
                "file:///tmp/bare-repo.git",
                "file:///tmp",
            ),
            (
                "file:///tmp/some/path/bare-repo",
                "file:///tmp/some/path",
            ),
        ],
        ids=[
            "https-with-git-suffix",
            "https-no-git-suffix",
            "http-internal",
            "ssh-with-git-suffix",
            "ssh-no-git-suffix",
            "file-with-git-suffix",
            "file-deep-path",
        ],
    )
    def test_derive_gitbase_standard_url_forms(self, url: str, expected_gitbase: str) -> None:
        """_derive_gitbase_from_catalog_source returns correct GITBASE for standard URL forms."""
        from kanon_cli.commands.add import _derive_gitbase_from_catalog_source

        result = _derive_gitbase_from_catalog_source(url)
        assert result == expected_gitbase, (
            f"GITBASE derivation mismatch for URL {url!r}.\n  Expected: {expected_gitbase!r}\n  Got     : {result!r}"
        )

    @pytest.mark.parametrize(
        "scp_url,expected_gitbase",
        [
            (
                "git@github.com:my-org/my-repo.git",
                "git@github.com:my-org",
            ),
            (
                "git@github.com:my-org/my-repo",
                "git@github.com:my-org",
            ),
            (
                "git@gitlab.example.com:team/project.git",
                "git@gitlab.example.com:team",
            ),
        ],
        ids=["scp-with-git-suffix", "scp-no-git-suffix", "scp-custom-host"],
    )
    def test_derive_gitbase_scp_shorthand_form(self, scp_url: str, expected_gitbase: str) -> None:
        """_derive_gitbase_from_catalog_source handles git@host:org/repo SCP shorthand."""
        from kanon_cli.commands.add import _derive_gitbase_from_catalog_source

        result = _derive_gitbase_from_catalog_source(scp_url)
        assert result == expected_gitbase, (
            f"GITBASE derivation mismatch for SCP URL {scp_url!r}.\n"
            f"  Expected: {expected_gitbase!r}\n"
            f"  Got     : {result!r}"
        )

    def test_derive_gitbase_raises_on_empty_url(self) -> None:
        """_derive_gitbase_from_catalog_source raises ValueError on empty URL."""
        from kanon_cli.commands.add import _derive_gitbase_from_catalog_source

        with pytest.raises(ValueError, match="catalog-source URL is required"):
            _derive_gitbase_from_catalog_source("")

    def test_derive_gitbase_raises_on_no_scheme(self) -> None:
        """_derive_gitbase_from_catalog_source raises CatalogSourceURLDerivationError on schemeless URL."""
        from kanon_cli.commands.add import (
            CatalogSourceURLDerivationError,
            _derive_gitbase_from_catalog_source,
        )

        with pytest.raises(CatalogSourceURLDerivationError) as exc_info:
            _derive_gitbase_from_catalog_source("not-a-valid-url/org/repo")
        assert "no scheme" in str(exc_info.value).lower()

    def test_derive_gitbase_raises_on_scheme_without_netloc(self) -> None:
        """_derive_gitbase_from_catalog_source raises when scheme is present but netloc is missing."""
        from kanon_cli.commands.add import (
            CatalogSourceURLDerivationError,
            _derive_gitbase_from_catalog_source,
        )

        with pytest.raises(CatalogSourceURLDerivationError) as exc_info:
            _derive_gitbase_from_catalog_source("ftp:")
        err_msg = str(exc_info.value)
        assert "no host" in err_msg.lower() or "authority" in err_msg.lower()

    def test_catalog_source_url_derivation_error_str_format(self) -> None:
        """CatalogSourceURLDerivationError.__str__ follows the standard ERROR: shape."""
        from kanon_cli.commands.add import CatalogSourceURLDerivationError

        err = CatalogSourceURLDerivationError("bad://url", "test reason")
        msg = str(err)
        assert "ERROR:" in msg
        assert "bad://url" in msg
        assert "test reason" in msg
        assert "KANON_GITBASE" in msg

    def test_catalog_source_url_derivation_error_is_value_error(self) -> None:
        """CatalogSourceURLDerivationError is a subclass of ValueError."""
        from kanon_cli.commands.add import CatalogSourceURLDerivationError

        err = CatalogSourceURLDerivationError("url", "reason")
        assert isinstance(err, ValueError)
        assert err.url == "url"
        assert err.reason == "reason"


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


@pytest.mark.unit
class TestRunAddMissingCatalogSource:
    """run_add exits non-zero when no catalog source is configured."""

    def test_missing_catalog_source_exits_nonzero(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_add exits non-zero when catalog_source is None and env var is absent."""
        import argparse

        from kanon_cli.commands.add import run_add

        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)
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
class TestRunAddGitbaseDerivationError:
    """run_add exits non-zero when GITBASE cannot be derived from the catalog-source URL."""

    def test_unparseable_catalog_source_url_exits_nonzero(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_add exits non-zero and prints ERROR when catalog-source URL has no scheme."""
        import argparse

        from kanon_cli.commands.add import run_add

        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)

        args = argparse.Namespace(
            catalog_source="not-valid-url/org/repo@main",
            kanon_file="./.kanon",
            entries=["entry-a"],
            force=False,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc_info:
            run_add(args)
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err
        assert "GITBASE" in captured.err


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
        assert "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0" in content
        assert "KANON_SOURCE_entry_a_PATH=" in content


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

        assert not (tmp_path / ".kanon-data").exists(), (
            "run_add --dry-run must not create .kanon-data/; "
            "the workspace lock is only acquired on the non-dry-run write path"
        )


@pytest.mark.unit
class TestResolveSpecNoPep440Tags:
    """_resolve_spec exits non-zero when no PEP 440-valid tags exist."""

    def test_non_pep440_tags_only_exits_nonzero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When all tags fail PEP 440 parsing, exits non-zero with error message."""
        from unittest.mock import patch

        from kanon_cli.commands.add import _resolve_spec

        non_pep440_tags = ["refs/tags/v-alpha", "refs/tags/nightly-build", "refs/tags/dev"]
        with patch("kanon_cli.commands.add._list_tags", return_value=non_pep440_tags):
            with pytest.raises(SystemExit) as exc_info:
                _resolve_spec("https://example.com/repo.git", None)
        assert exc_info.value.code != 0

    def test_non_pep440_tags_error_message_mentions_pep440(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Error message names the PEP 440 constraint requirement."""
        from unittest.mock import patch

        from kanon_cli.commands.add import _resolve_spec

        non_pep440_tags = ["refs/tags/nightly", "refs/tags/dev-branch"]
        with patch("kanon_cli.commands.add._list_tags", return_value=non_pep440_tags):
            with pytest.raises(SystemExit):
                _resolve_spec("https://example.com/repo.git", None)
        captured = capsys.readouterr()
        assert "PEP 440" in captured.err
        assert "Skipped non-PEP-440 tags:" in captured.err

    def test_non_pep440_tags_lists_skipped_names(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Error message lists the skipped non-PEP-440 tag names."""
        from unittest.mock import patch

        from kanon_cli.commands.add import _resolve_spec

        non_pep440_tags = ["refs/tags/foo-alpha", "refs/tags/bar-beta"]
        with patch("kanon_cli.commands.add._list_tags", return_value=non_pep440_tags):
            with pytest.raises(SystemExit):
                _resolve_spec("https://example.com/repo.git", None)
        captured = capsys.readouterr()
        assert "foo-alpha" in captured.err or "bar-beta" in captured.err

    @pytest.mark.parametrize(
        "tags,expected_cap_message",
        [
            (
                [f"refs/tags/nightly-{i}" for i in range(20)],
                True,
            ),
            (
                ["refs/tags/just-one-bad-tag"],
                False,
            ),
        ],
        ids=["many-tags-truncated", "single-tag-no-truncation"],
    )
    def test_non_pep440_tags_display_cap_applied(
        self,
        tags: list[str],
        expected_cap_message: bool,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Display cap message appears when skipped count exceeds TAG_ERROR_DISPLAY_CAP."""
        from unittest.mock import patch

        from kanon_cli.commands.add import _resolve_spec
        from kanon_cli.constants import TAG_ERROR_DISPLAY_CAP

        with patch("kanon_cli.commands.add._list_tags", return_value=tags):
            with pytest.raises(SystemExit):
                _resolve_spec("https://example.com/repo.git", None)
        captured = capsys.readouterr()
        cap_phrase = f"showing first {TAG_ERROR_DISPLAY_CAP} of"
        if expected_cap_message:
            assert cap_phrase in captured.err
        else:
            assert cap_phrase not in captured.err


@pytest.mark.unit
class TestCheckWithinRequestCollisions:
    """_check_within_request_collisions detects duplicate entry names."""

    def test_collision_exits_nonzero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Two entries normalising to the same source name triggers non-zero exit."""
        from kanon_cli.commands.add import _check_within_request_collisions

        with pytest.raises(SystemExit) as exc_info:
            _check_within_request_collisions(["entry-a", "entry_a"])
        assert exc_info.value.code != 0

    def test_collision_error_names_both_entries(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Error message includes both colliding entry names."""
        from kanon_cli.commands.add import _check_within_request_collisions

        with pytest.raises(SystemExit):
            _check_within_request_collisions(["my-pkg", "my_pkg"])
        captured = capsys.readouterr()
        assert "my-pkg" in captured.err
        assert "my_pkg" in captured.err

    def test_collision_error_mentions_normalised_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Error message mentions the normalised source name."""
        from kanon_cli.commands.add import _check_within_request_collisions

        with pytest.raises(SystemExit):
            _check_within_request_collisions(["foo-bar", "foo_bar"])
        captured = capsys.readouterr()
        assert "foo_bar" in captured.err

    def test_no_collision_returns_none(self) -> None:
        """Distinct entry names return without raising."""
        from kanon_cli.commands.add import _check_within_request_collisions

        result = _check_within_request_collisions(["entry-a", "entry-b", "entry-c"])
        assert result is None


@pytest.mark.unit
class TestReadExistingTripleBlock:
    """_read_existing_source_block reads an existing .kanon block."""

    def test_reads_url_revision_path_from_existing_file(self, tmp_path: pathlib.Path) -> None:
        """Returns the URL, REVISION, PATH values for a known source name."""
        from kanon_cli.commands.add import _read_existing_source_block

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_my_pkg_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_my_pkg_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_my_pkg_PATH=repo-specs/my-pkg-marketplace.xml\n"
        )
        url, revision, path = _read_existing_source_block(kanon_file, "my_pkg")
        assert url == "https://example.com/repo.git"
        assert revision == "refs/tags/1.0.0"
        assert path == "repo-specs/my-pkg-marketplace.xml"

    def test_returns_none_triple_for_nonexistent_file(self, tmp_path: pathlib.Path) -> None:
        """Returns (None, None, None) when the .kanon file does not exist."""
        from kanon_cli.commands.add import _read_existing_source_block

        kanon_file = tmp_path / ".kanon"
        url, revision, path = _read_existing_source_block(kanon_file, "any_name")
        assert url is None
        assert revision is None
        assert path is None

    def test_returns_none_triple_for_unknown_source_name(self, tmp_path: pathlib.Path) -> None:
        """Returns (None, None, None) when the source name is not in the file."""
        from kanon_cli.commands.add import _read_existing_source_block

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_other_pkg_URL=https://example.com/other.git\n"
            "KANON_SOURCE_other_pkg_REF=refs/tags/2.0.0\n"
            "KANON_SOURCE_other_pkg_PATH=repo-specs/other-marketplace.xml\n"
        )
        url, revision, path = _read_existing_source_block(kanon_file, "my_pkg")
        assert url is None
        assert revision is None
        assert path is None


@pytest.mark.unit
class TestSameNameGuard:
    """_emit_same_name_guard_error fails fast with a diff + the guiding message."""

    def test_same_name_guard_exits_nonzero(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A re-add of an existing alias (same source@ref) without --force exits non-zero."""
        from kanon_cli.commands.add import _emit_same_name_guard_error

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_my_pkg_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_my_pkg_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_my_pkg_PATH=repo-specs/my-pkg-marketplace.xml\n",
            encoding="utf-8",
        )
        with pytest.raises(SystemExit) as exc_info:
            _emit_same_name_guard_error(
                kanon_file=kanon_file,
                source_name="my_pkg",
                new_url="https://example.com/repo.git",
                new_ref="==1.0.0",
                new_path="repo-specs/my-pkg-marketplace.xml",
            )
        assert exc_info.value.code != 0

    def test_same_name_guard_names_alias_and_shows_diff_and_guidance(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The guard error names the alias, renders a +/- diff, and points to --force / remove."""
        from kanon_cli.commands.add import _emit_same_name_guard_error

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_my_pkg_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_my_pkg_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_my_pkg_PATH=repo-specs/my-pkg-marketplace.xml\n",
            encoding="utf-8",
        )
        with pytest.raises(SystemExit):
            _emit_same_name_guard_error(
                kanon_file=kanon_file,
                source_name="my_pkg",
                new_url="https://example.com/repo.git",
                new_ref="==2.0.0",
                new_path="repo-specs/my-pkg-marketplace.xml",
            )
        err = capsys.readouterr().err
        assert "my_pkg" in err

        assert "-KANON_SOURCE_my_pkg_REF=refs/tags/1.0.0" in err
        assert "+KANON_SOURCE_my_pkg_REF===2.0.0" in err

        assert "--force" in err
        assert "kanon remove my_pkg" in err


@pytest.mark.unit
class TestResolveEntryAlias:
    """_resolve_entry_alias implements the deterministic auto-suffix model."""

    _URL_A = "https://github.com/org-a/pkg.git"
    _URL_B = "https://github.com/caylent/caylent-private-kanon.git"

    def test_free_base_alias_is_new(self) -> None:
        """An unused base alias resolves to itself with mode 'new'."""
        from kanon_cli.commands.add import _resolve_entry_alias

        alias, mode = _resolve_entry_alias({}, "history", self._URL_A, "1.0.0", force=False)
        assert (alias, mode) == ("history", "new")

    def test_cross_source_collision_appends_repo_suffix(self) -> None:
        """A taken bare alias from a DIFFERENT source auto-suffixes to base_repo."""
        from kanon_cli.commands.add import _resolve_entry_alias

        existing = {"history": (self._URL_A, "1.0.0")}
        alias, mode = _resolve_entry_alias(existing, "history", self._URL_B, ">=2.0.0,<3.0.0", force=False)
        assert (alias, mode) == ("history_caylent_private_kanon", "new")

    def test_same_repo_different_ref_appends_ref_suffix(self) -> None:
        """When the repo suffix still collides (same repo, different ref) the ref suffix is added."""
        from kanon_cli.commands.add import _resolve_entry_alias

        existing = {
            "history": (self._URL_A, "1.0.0"),
            "history_caylent_private_kanon": (self._URL_B, ">=9.0.0,<10.0.0"),
        }
        alias, mode = _resolve_entry_alias(existing, "history", self._URL_B, ">=0.1.0,<1.0.0", force=False)
        assert (alias, mode) == ("history_caylent_private_kanon_0_1_0_1_0_0", "new")

    def test_same_source_same_ref_without_force_is_duplicate(self) -> None:
        """Re-add of the same alias at the same source@ref (no --force) is a duplicate."""
        from kanon_cli.commands.add import _resolve_entry_alias

        existing = {"history": (self._URL_A, "1.0.0")}
        alias, mode = _resolve_entry_alias(existing, "history", self._URL_A, "1.0.0", force=False)
        assert (alias, mode) == ("history", "duplicate")

    def test_same_source_same_ref_with_force_is_overwrite(self) -> None:
        """Re-add of the same alias at the same source@ref with --force is a force_overwrite."""
        from kanon_cli.commands.add import _resolve_entry_alias

        existing = {"history": (self._URL_A, "1.0.0")}
        alias, mode = _resolve_entry_alias(existing, "history", self._URL_A, "1.0.0", force=True)
        assert (alias, mode) == ("history", "force_overwrite")

    def test_all_candidates_taken_by_distinct_sources_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When every candidate is taken by a distinct source the add fails fast."""
        from kanon_cli.commands.add import _resolve_entry_alias

        url_c = "https://github.com/org-c/pkg.git"
        existing = {
            "history": (self._URL_A, "1.0.0"),
            "history_caylent_private_kanon": (self._URL_B, "2.0.0"),
            "history_caylent_private_kanon_3_0_0": (url_c, "3.0.0"),
        }

        with pytest.raises(SystemExit) as exc_info:
            _resolve_entry_alias(existing, "history", self._URL_B, "3.0.0", force=False)
        assert exc_info.value.code != 0
        assert "--as" in capsys.readouterr().err


@pytest.mark.unit
class TestResolveOverrideAlias:
    """_resolve_override_alias never suffixes an explicit --as alias."""

    _URL_A = "https://github.com/org-a/pkg.git"
    _URL_B = "https://github.com/org-b/pkg.git"

    def test_free_alias_is_new(self) -> None:
        """A free --as alias resolves to itself with mode 'new'."""
        from kanon_cli.commands.add import _resolve_override_alias

        alias, mode = _resolve_override_alias({}, "myalias", self._URL_A, "1.0.0", force=False)
        assert (alias, mode) == ("myalias", "new")

    def test_taken_by_same_source_without_force_is_duplicate(self) -> None:
        """An --as alias already mapped to the same source@ref is a duplicate (no --force)."""
        from kanon_cli.commands.add import _resolve_override_alias

        existing = {"myalias": (self._URL_A, "1.0.0")}
        alias, mode = _resolve_override_alias(existing, "myalias", self._URL_A, "1.0.0", force=False)
        assert (alias, mode) == ("myalias", "duplicate")

    def test_taken_by_different_source_without_force_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        """An --as alias already mapped to a DIFFERENT source (no --force) fails fast."""
        from kanon_cli.commands.add import _resolve_override_alias

        existing = {"myalias": (self._URL_A, "1.0.0")}
        with pytest.raises(SystemExit) as exc_info:
            _resolve_override_alias(existing, "myalias", self._URL_B, "2.0.0", force=False)
        assert exc_info.value.code != 0
        err = capsys.readouterr().err
        assert "myalias" in err
        assert "--force" in err

    def test_taken_by_different_source_with_force_is_overwrite(self) -> None:
        """With --force, an --as alias mapped to a different source is an explicit overwrite."""
        from kanon_cli.commands.add import _resolve_override_alias

        existing = {"myalias": (self._URL_A, "1.0.0")}
        alias, mode = _resolve_override_alias(existing, "myalias", self._URL_B, "2.0.0", force=True)
        assert (alias, mode) == ("myalias", "force_overwrite")


@pytest.mark.unit
class TestAliasSanitization:
    """_sanitize_alias_fragment / _source_repo_fragment / _validate_alias_override."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("main", "main"),
            (">=0.1.0,<1.0.0", "0_1_0_1_0_0"),
            ("caylent-private-kanon", "caylent_private_kanon"),
            ("__leading_trailing__", "leading_trailing"),
            ("a---b", "a_b"),
            ("", ""),
        ],
        ids=["branch", "constraint", "repo-name", "trim", "collapse", "empty"],
    )
    def test_sanitize_alias_fragment(self, value: str, expected: str) -> None:
        """Non-charset runs collapse to a single '_'; leading/trailing '_' trimmed; never '__'."""
        from kanon_cli.commands.add import _sanitize_alias_fragment

        result = _sanitize_alias_fragment(value)
        assert result == expected
        assert "__" not in result

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://github.com/caylent/caylent-private-kanon.git", "caylent_private_kanon"),
            ("git@github.com:org/my-repo.git", "my_repo"),
            ("file:///tmp/bare-repo.git", "bare_repo"),
            ("https://host/org/repo", "repo"),
        ],
        ids=["https-git", "scp", "file", "no-git-suffix"],
    )
    def test_source_repo_fragment(self, url: str, expected: str) -> None:
        """The repo fragment is the sanitized basename of the URL path (sans .git)."""
        from kanon_cli.commands.add import _source_repo_fragment

        assert _source_repo_fragment(url) == expected

    @pytest.mark.parametrize(
        "alias",
        ["good_alias", "Alias123", "a"],
        ids=["underscore", "mixed-case-digits", "single"],
    )
    def test_validate_alias_override_accepts_legal(self, alias: str) -> None:
        """A legal alias passes validation unchanged."""
        from kanon_cli.commands.add import _validate_alias_override

        assert _validate_alias_override(alias) == alias

    @pytest.mark.parametrize(
        "alias",
        ["", "bad-alias", "has space", "double__under", "dot.alias"],
        ids=["empty", "hyphen", "space", "double-underscore", "dot"],
    )
    def test_validate_alias_override_rejects_illegal(self, alias: str) -> None:
        """An illegal alias raises AliasOverrideError (fail fast, no silent sanitize)."""
        from kanon_cli.commands.add import AliasOverrideError, _validate_alias_override

        with pytest.raises(AliasOverrideError):
            _validate_alias_override(alias)


@pytest.mark.unit
class TestReadAllSourceAliases:
    """_read_all_source_aliases maps each alias to its (url, ref) coordinates."""

    def test_reads_multiple_aliases_in_order(self, tmp_path: pathlib.Path) -> None:
        """Every alias block is read with its URL and REF, in first-seen order."""
        from kanon_cli.commands.add import _read_all_source_aliases

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "CLAUDE_MARKETPLACES_DIR=/tmp/mk\n"
            "KANON_SOURCE_alpha_URL=https://example.com/a.git\n"
            "KANON_SOURCE_alpha_REF=1.0.0\n"
            "KANON_SOURCE_alpha_PATH=p\n"
            "KANON_SOURCE_beta_URL=https://example.com/b.git\n"
            "KANON_SOURCE_beta_REF=2.0.0\n",
            encoding="utf-8",
        )
        result = _read_all_source_aliases(kanon_file)
        assert result == {
            "alpha": ("https://example.com/a.git", "1.0.0"),
            "beta": ("https://example.com/b.git", "2.0.0"),
        }
        assert list(result) == ["alpha", "beta"]

    def test_absent_file_is_empty(self, tmp_path: pathlib.Path) -> None:
        """A missing .kanon file yields an empty alias map."""
        from kanon_cli.commands.add import _read_all_source_aliases

        assert _read_all_source_aliases(tmp_path / ".kanon") == {}


@pytest.mark.unit
class TestOverwriteTripleBlock:
    """_overwrite_source_block replaces an existing triple in the .kanon file."""

    def test_overwrites_existing_triple(self, tmp_path: pathlib.Path) -> None:
        """Replaces old URL/REVISION/PATH lines with new ones."""
        from kanon_cli.commands.add import _overwrite_source_block

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=https://example.com/org\n"
            "KANON_SOURCE_my_pkg_URL=https://example.com/old.git\n"
            "KANON_SOURCE_my_pkg_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_my_pkg_PATH=repo-specs/old-marketplace.xml\n"
        )
        new_lines = [
            "KANON_SOURCE_my_pkg_URL=https://example.com/new.git",
            "KANON_SOURCE_my_pkg_REF=refs/tags/2.0.0",
            "KANON_SOURCE_my_pkg_PATH=repo-specs/new-marketplace.xml",
        ]
        _overwrite_source_block(kanon_file, "my_pkg", new_lines)
        content = kanon_file.read_text()
        assert "KANON_SOURCE_my_pkg_URL=https://example.com/new.git" in content
        assert "KANON_SOURCE_my_pkg_REF=refs/tags/2.0.0" in content
        assert "KANON_SOURCE_my_pkg_PATH=repo-specs/new-marketplace.xml" in content
        assert "https://example.com/old.git" not in content
        assert "refs/tags/1.0.0" not in content

    def test_preserves_other_content(self, tmp_path: pathlib.Path) -> None:
        """Lines not belonging to the overwritten triple are preserved."""
        from kanon_cli.commands.add import _overwrite_source_block

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=https://example.com/org\n"
            "KANON_SOURCE_my_pkg_URL=https://example.com/old.git\n"
            "KANON_SOURCE_my_pkg_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_my_pkg_PATH=repo-specs/old-marketplace.xml\n"
            "KANON_SOURCE_other_pkg_URL=https://other.example.com/repo.git\n"
        )
        new_lines = [
            "KANON_SOURCE_my_pkg_URL=https://example.com/new.git",
            "KANON_SOURCE_my_pkg_REF=refs/tags/2.0.0",
            "KANON_SOURCE_my_pkg_PATH=repo-specs/new-marketplace.xml",
        ]
        _overwrite_source_block(kanon_file, "my_pkg", new_lines)
        content = kanon_file.read_text()
        assert "GITBASE=https://example.com/org" in content
        assert "KANON_SOURCE_other_pkg_URL=https://other.example.com/repo.git" in content

    def test_overwrite_prints_summary_to_stdout(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """_overwrite_source_block prints a summary mentioning the source name."""
        from kanon_cli.commands.add import _overwrite_source_block

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_my_pkg_URL=https://example.com/old.git\n"
            "KANON_SOURCE_my_pkg_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_my_pkg_PATH=repo-specs/old-marketplace.xml\n"
        )
        new_lines = [
            "KANON_SOURCE_my_pkg_URL=https://example.com/new.git",
            "KANON_SOURCE_my_pkg_REF=refs/tags/2.0.0",
            "KANON_SOURCE_my_pkg_PATH=repo-specs/new-marketplace.xml",
        ]
        _overwrite_source_block(kanon_file, "my_pkg", new_lines)
        captured = capsys.readouterr()
        assert "my_pkg" in captured.out
        assert "Overwrote" in captured.out


@pytest.mark.unit
class TestRenderDryRunDiff:
    """_render_dry_run_diff prints correct diff lines."""

    def test_no_force_prints_added_lines(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Without force, all new lines are printed with '+' prefix."""
        from kanon_cli.commands.add import _render_dry_run_diff

        dest = tmp_path / ".kanon"
        new_lines = [
            "KANON_SOURCE_my_pkg_URL=https://example.com/repo.git",
            "KANON_SOURCE_my_pkg_REF=refs/tags/1.0.0",
            "KANON_SOURCE_my_pkg_PATH=repo-specs/my-pkg-marketplace.xml",
        ]
        _render_dry_run_diff(dest, "my_pkg", new_lines, force=False)
        captured = capsys.readouterr()
        for line in new_lines:
            assert f"+{line}" in captured.out

    def test_force_with_existing_block_shows_removed_and_added_lines(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With force=True and existing block, shows '-' old lines then '+' new lines."""
        from kanon_cli.commands.add import _render_dry_run_diff

        dest = tmp_path / ".kanon"
        dest.write_text(
            "KANON_SOURCE_my_pkg_URL=https://example.com/old.git\n"
            "KANON_SOURCE_my_pkg_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_my_pkg_PATH=repo-specs/old-marketplace.xml\n"
        )
        new_lines = [
            "KANON_SOURCE_my_pkg_URL=https://example.com/new.git",
            "KANON_SOURCE_my_pkg_REF=refs/tags/2.0.0",
            "KANON_SOURCE_my_pkg_PATH=repo-specs/new-marketplace.xml",
        ]
        _render_dry_run_diff(dest, "my_pkg", new_lines, force=True)
        captured = capsys.readouterr()
        assert "-KANON_SOURCE_my_pkg_URL=https://example.com/old.git" in captured.out
        assert "+KANON_SOURCE_my_pkg_URL=https://example.com/new.git" in captured.out

    def test_force_with_no_existing_block_falls_through_to_plus_lines(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With force=True but no existing block, prints '+' prefixed lines."""
        from kanon_cli.commands.add import _render_dry_run_diff

        dest = tmp_path / ".kanon"
        dest.write_text("GITBASE=https://example.com/org\n")
        new_lines = [
            "KANON_SOURCE_my_pkg_URL=https://example.com/repo.git",
            "KANON_SOURCE_my_pkg_REF=refs/tags/1.0.0",
            "KANON_SOURCE_my_pkg_PATH=repo-specs/my-pkg-marketplace.xml",
        ]
        _render_dry_run_diff(dest, "my_pkg", new_lines, force=True)
        captured = capsys.readouterr()
        for line in new_lines:
            assert f"+{line}" in captured.out


@pytest.mark.unit
class TestRunAddForce:
    """run_add --force overwrites an existing triple block."""

    def _make_xml_file(self, tmp_path: pathlib.Path, name: str) -> pathlib.Path:
        """Create a minimal XML catalog file for the given entry name."""
        import textwrap

        xml_path = tmp_path / "repo" / "repo-specs" / f"{name}-marketplace.xml"
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        xml_path.write_text(
            textwrap.dedent(f"""\
                <?xml version="1.0" encoding="UTF-8"?>
                <manifest>
                  <catalog-metadata>
                    <name>{name}</name>
                    <display-name>{name} Display</display-name>
                    <description>Test entry.</description>
                    <version>1.0.0</version>
                    <type>plugin</type>
                    <owner-name>Owner</owner-name>
                    <owner-email>o@example.com</owner-email>
                    <keywords>test</keywords>
                  </catalog-metadata>
                </manifest>
            """)
        )
        return xml_path

    def test_run_add_force_overwrites_same_source_block(self, tmp_path: pathlib.Path) -> None:
        """run_add --force overwrites the alias block when re-adding the same source@ref.

        The existing block is keyed by the same alias and the same source URL +
        resolved ref the add resolves to, so the alias resolution returns
        ``force_overwrite`` (a re-add of the existing package, spec Section 4.2)
        rather than auto-suffixing to a fresh alias. The PATH is refreshed by the
        overwrite while the URL / REF are re-pinned.
        """
        import argparse
        from unittest.mock import patch

        from kanon_cli.commands.add import run_add

        kanon_file = tmp_path / ".kanon"

        kanon_file.write_text(
            "GITBASE=https://example.com/org\n"
            "KANON_SOURCE_force_pkg_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_force_pkg_REF=refs/tags/2.0.0\n"
            "KANON_SOURCE_force_pkg_PATH=repo-specs/stale-path.xml\n",
            encoding="utf-8",
        )
        meta = CatalogMetadata(
            name="force-pkg",
            display_name="Force Pkg",
            description="Test.",
            version="2.0.0",
        )
        xml_path = self._make_xml_file(tmp_path, "force-pkg")
        manifest_root = tmp_path / "repo"

        args = argparse.Namespace(
            catalog_source="https://example.com/repo.git@main",
            kanon_file=str(kanon_file),
            entries=["force-pkg"],
            force=True,
            dry_run=False,
            alias_override=None,
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
                return_value="refs/tags/2.0.0",
            ),
        ):
            result = run_add(args)

        assert result == 0
        content = kanon_file.read_text()

        assert "KANON_SOURCE_force_pkg_REF=refs/tags/2.0.0" in content
        assert "KANON_SOURCE_force_pkg_repo_URL=" not in content

        assert "repo-specs/force-pkg-marketplace.xml" in content
        assert "repo-specs/stale-path.xml" not in content

    def test_run_add_cross_source_collision_auto_suffixes(self, tmp_path: pathlib.Path) -> None:
        """A same-NAME add from a DIFFERENT source auto-suffixes; the existing block is untouched."""
        import argparse
        from unittest.mock import patch

        from kanon_cli.commands.add import run_add

        kanon_file = tmp_path / ".kanon"

        kanon_file.write_text(
            "GITBASE=https://example.com/org\n"
            "KANON_SOURCE_force_pkg_URL=https://example.com/other.git\n"
            "KANON_SOURCE_force_pkg_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_force_pkg_PATH=repo-specs/force-pkg-marketplace.xml\n",
            encoding="utf-8",
        )
        meta = CatalogMetadata(
            name="force-pkg",
            display_name="Force Pkg",
            description="Test.",
            version="2.0.0",
        )
        xml_path = self._make_xml_file(tmp_path, "force-pkg")
        manifest_root = tmp_path / "repo"

        args = argparse.Namespace(
            catalog_source="https://example.com/repo.git@main",
            kanon_file=str(kanon_file),
            entries=["force-pkg"],
            force=False,
            dry_run=False,
            alias_override=None,
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
                return_value="refs/tags/2.0.0",
            ),
        ):
            result = run_add(args)

        assert result == 0
        content = kanon_file.read_text()

        assert "KANON_SOURCE_force_pkg_repo_URL=https://example.com/repo.git" in content
        assert "KANON_SOURCE_force_pkg_URL=https://example.com/other.git" in content

    def test_run_add_force_new_entry_appends_when_no_existing_block(self, tmp_path: pathlib.Path) -> None:
        """run_add --force appends when the source name is not already present."""
        import argparse
        from unittest.mock import patch

        from kanon_cli.commands.add import run_add

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("GITBASE=https://example.com/org\n")
        meta = CatalogMetadata(
            name="new-pkg",
            display_name="New Pkg",
            description="Test.",
            version="1.0.0",
        )
        xml_path = self._make_xml_file(tmp_path, "new-pkg")
        manifest_root = tmp_path / "repo"

        args = argparse.Namespace(
            catalog_source="https://example.com/repo.git@main",
            kanon_file=str(kanon_file),
            entries=["new-pkg"],
            force=True,
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
        content = kanon_file.read_text()
        assert "KANON_SOURCE_new_pkg_URL=" in content
        assert "KANON_SOURCE_new_pkg_REF=refs/tags/1.0.0" in content

    def test_run_add_dry_run_force_prints_diff_with_removed_lines(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """run_add --dry-run --force prints '-' and '+' diff lines for an existing block."""
        import argparse
        from unittest.mock import patch

        from kanon_cli.commands.add import run_add

        kanon_file = tmp_path / ".kanon"

        kanon_file.write_text(
            "GITBASE=https://example.com/org\n"
            "KANON_SOURCE_dry_pkg_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_dry_pkg_REF=refs/tags/2.0.0\n"
            "KANON_SOURCE_dry_pkg_PATH=repo-specs/stale-path.xml\n",
            encoding="utf-8",
        )
        meta = CatalogMetadata(
            name="dry-pkg",
            display_name="Dry Pkg",
            description="Test.",
            version="2.0.0",
        )
        xml_path = self._make_xml_file(tmp_path, "dry-pkg")
        manifest_root = tmp_path / "repo"

        args = argparse.Namespace(
            catalog_source="https://example.com/repo.git@main",
            kanon_file=str(kanon_file),
            entries=["dry-pkg"],
            force=True,
            dry_run=True,
            alias_override=None,
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
                return_value="refs/tags/2.0.0",
            ),
        ):
            result = run_add(args)

        assert result == 0
        captured = capsys.readouterr()

        assert "-KANON_SOURCE_dry_pkg_PATH=repo-specs/stale-path.xml" in captured.out
        assert "+KANON_SOURCE_dry_pkg_PATH=" in captured.out

        content = kanon_file.read_text()
        assert "repo-specs/stale-path.xml" in content


@pytest.mark.unit
class TestResolveMarketplaceFlag:
    """Branch coverage for _resolve_marketplace_flag (item 15, FR-17).

    Precedence: --marketplace-install (flag_override=True) forces on but only on
    a marketplace-typed entry (else a pretty MarketplaceInstallError);
    --no-marketplace-install (flag_override=False) forces off;
    no flag (flag_override=None) auto-detects from the catalog <type>.
    """

    def test_override_true_on_marketplace_type_returns_true(self) -> None:
        """flag_override=True on a claude-marketplace entry resolves to True."""
        from kanon_cli.commands.add import _resolve_marketplace_flag
        from kanon_cli.constants import CATALOG_TYPE_CLAUDE_MARKETPLACE

        result = _resolve_marketplace_flag(
            entry_name="mp-entry",
            entry_type=CATALOG_TYPE_CLAUDE_MARKETPLACE,
            flag_override=True,
        )
        assert result is True

    def test_override_true_on_non_marketplace_type_raises_with_actionable_message(self) -> None:
        """flag_override=True on a regular type raises MarketplaceInstallError naming the entry."""
        from kanon_cli.commands.add import MarketplaceInstallError, _resolve_marketplace_flag

        with pytest.raises(MarketplaceInstallError) as exc_info:
            _resolve_marketplace_flag(
                entry_name="plain-entry",
                entry_type="plugin",
                flag_override=True,
            )
        message = str(exc_info.value)
        assert "requires catalog entry" in message
        assert "plain-entry" in message
        assert "'plugin'" in message
        assert exc_info.value.entry_name == "plain-entry"
        assert exc_info.value.entry_type == "plugin"

    def test_override_true_on_absent_type_raises_with_absent_in_message(self) -> None:
        """flag_override=True on an entry with no <type> raises, rendering the type as absent."""
        from kanon_cli.commands.add import MarketplaceInstallError, _resolve_marketplace_flag

        with pytest.raises(MarketplaceInstallError) as exc_info:
            _resolve_marketplace_flag(
                entry_name="typeless-entry",
                entry_type=None,
                flag_override=True,
            )
        message = str(exc_info.value)
        assert "requires catalog entry" in message
        assert "typeless-entry" in message
        assert "absent" in message

    def test_override_false_returns_false_even_on_marketplace_type(self) -> None:
        """flag_override=False forces off regardless of the catalog <type>."""
        from kanon_cli.commands.add import _resolve_marketplace_flag
        from kanon_cli.constants import CATALOG_TYPE_CLAUDE_MARKETPLACE

        result = _resolve_marketplace_flag(
            entry_name="mp-entry",
            entry_type=CATALOG_TYPE_CLAUDE_MARKETPLACE,
            flag_override=False,
        )
        assert result is False

    def test_override_none_auto_detects_marketplace_type_as_true(self) -> None:
        """flag_override=None defers to _is_marketplace_type, which is True for a marketplace type."""
        from kanon_cli.commands.add import _resolve_marketplace_flag
        from kanon_cli.constants import CATALOG_TYPE_CLAUDE_MARKETPLACE

        result = _resolve_marketplace_flag(
            entry_name="mp-entry",
            entry_type=CATALOG_TYPE_CLAUDE_MARKETPLACE,
            flag_override=None,
        )
        assert result is True

    def test_override_none_auto_detects_regular_type_as_false(self) -> None:
        """flag_override=None on a regular type auto-detects to False (no error)."""
        from kanon_cli.commands.add import _resolve_marketplace_flag

        result = _resolve_marketplace_flag(
            entry_name="plain-entry",
            entry_type="plugin",
            flag_override=None,
        )
        assert result is False

    def test_override_none_auto_detects_absent_type_as_false(self) -> None:
        """flag_override=None on an absent <type> auto-detects to False (None is not marketplace)."""
        from kanon_cli.commands.add import _resolve_marketplace_flag

        result = _resolve_marketplace_flag(
            entry_name="typeless-entry",
            entry_type=None,
            flag_override=None,
        )
        assert result is False


@pytest.mark.unit
class TestRunAddMarketplaceLine:
    """run_add writes the per-alias _MARKETPLACE line + notice per FR-17 (item 15).

    Exercises the full run_add path with the catalog clone / build mocked so the
    only variable is the entry's <type> and the --marketplace-install flag.
    """

    @staticmethod
    def _make_args(kanon_file: pathlib.Path, marketplace_install: bool | None) -> "argparse.Namespace":
        """Build a run_add argparse namespace for a single entry."""
        import argparse

        return argparse.Namespace(
            catalog_source="https://example.com/org/repo.git@main",
            kanon_file=str(kanon_file),
            entries=["entry-a"],
            force=False,
            dry_run=False,
            alias_override=None,
            marketplace_install=marketplace_install,
        )

    @staticmethod
    def _run_with_type(
        kanon_file: pathlib.Path,
        entry_type: str | None,
        marketplace_install: bool | None,
    ) -> int:
        """Run run_add with a single mocked catalog entry of the given <type>."""
        from unittest.mock import patch

        from kanon_cli.commands.add import run_add

        meta = CatalogMetadata(
            name="entry-a",
            display_name="Entry A",
            description="Test.",
            version="1.0.0",
            type=entry_type,
        )
        manifest_root = kanon_file.parent / "repo"
        xml_path = manifest_root / "repo-specs" / "entry-a-marketplace.xml"
        url = "https://example.com/org/repo.git"
        args = TestRunAddMarketplaceLine._make_args(kanon_file, marketplace_install)
        with (
            patch(
                "kanon_cli.commands.add._resolve_manifest_repo_for_add",
                return_value=(manifest_root, url, "main"),
            ),
            patch(
                "kanon_cli.commands.add._build_entry_catalog",
                return_value=[(meta, xml_path, url)],
            ),
            patch(
                "kanon_cli.commands.add._resolve_spec",
                return_value="refs/tags/1.0.0",
            ),
        ):
            return run_add(args)

    def test_marketplace_type_writes_marketplace_true_line(self, tmp_path: pathlib.Path) -> None:
        """Adding a claude-marketplace entry writes KANON_SOURCE_<alias>_MARKETPLACE=true."""
        from kanon_cli.constants import CATALOG_TYPE_CLAUDE_MARKETPLACE

        kanon_file = tmp_path / ".kanon"
        assert self._run_with_type(kanon_file, CATALOG_TYPE_CLAUDE_MARKETPLACE, None) == 0
        content = kanon_file.read_text(encoding="utf-8")
        assert "KANON_SOURCE_entry_a_MARKETPLACE=true" in content

    def test_marketplace_type_prints_auto_detect_notice(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Auto-detected marketplace add prints a notice naming the type and the override flag."""
        from kanon_cli.constants import CATALOG_TYPE_CLAUDE_MARKETPLACE

        kanon_file = tmp_path / ".kanon"
        assert self._run_with_type(kanon_file, CATALOG_TYPE_CLAUDE_MARKETPLACE, None) == 0
        out = capsys.readouterr().out
        assert "Note:" in out
        assert CATALOG_TYPE_CLAUDE_MARKETPLACE in out
        assert "KANON_SOURCE_entry_a_MARKETPLACE=true" in out
        assert "--no-marketplace-install" in out

    def test_regular_type_writes_no_marketplace_line(self, tmp_path: pathlib.Path) -> None:
        """Adding a regular (plugin) entry writes no _MARKETPLACE line at all."""
        kanon_file = tmp_path / ".kanon"
        assert self._run_with_type(kanon_file, "plugin", None) == 0
        content = kanon_file.read_text(encoding="utf-8")
        assert "_MARKETPLACE" not in content

    def test_regular_type_prints_no_auto_detect_notice(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A regular add does not print the marketplace auto-detect notice."""
        kanon_file = tmp_path / ".kanon"
        assert self._run_with_type(kanon_file, "plugin", None) == 0
        out = capsys.readouterr().out
        assert "MARKETPLACE" not in out

    def test_force_flag_on_marketplace_type_writes_true_without_notice(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--marketplace-install on a marketplace type writes =true and suppresses the auto-detect notice."""
        from kanon_cli.constants import CATALOG_TYPE_CLAUDE_MARKETPLACE

        kanon_file = tmp_path / ".kanon"
        assert self._run_with_type(kanon_file, CATALOG_TYPE_CLAUDE_MARKETPLACE, True) == 0
        content = kanon_file.read_text(encoding="utf-8")
        assert "KANON_SOURCE_entry_a_MARKETPLACE=true" in content
        out = capsys.readouterr().out
        assert "Note:" not in out

    def test_no_marketplace_install_on_marketplace_type_omits_line(self, tmp_path: pathlib.Path) -> None:
        """--no-marketplace-install on a marketplace type omits the _MARKETPLACE line."""
        from kanon_cli.constants import CATALOG_TYPE_CLAUDE_MARKETPLACE

        kanon_file = tmp_path / ".kanon"
        assert self._run_with_type(kanon_file, CATALOG_TYPE_CLAUDE_MARKETPLACE, False) == 0
        content = kanon_file.read_text(encoding="utf-8")
        assert "_MARKETPLACE" not in content

    def test_marketplace_install_on_non_marketplace_type_exits_nonzero_with_pretty_error(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--marketplace-install on a regular type exits non-zero with the pretty error, not a traceback."""
        kanon_file = tmp_path / ".kanon"
        with pytest.raises(SystemExit) as exc_info:
            self._run_with_type(kanon_file, "plugin", True)
        assert exc_info.value.code != 0
        err = capsys.readouterr().err
        assert "--marketplace-install requires catalog entry" in err
        assert "entry-a" in err
        assert not kanon_file.exists()


_ADD_PY = pathlib.Path(__file__).resolve().parents[2] / "src" / "kanon_cli" / "commands" / "add.py"


@pytest.mark.unit
class TestAddPyUtf8EncodingSweep:
    """AC-12: all read_text/write_text calls in commands/add.py specify encoding."""

    def test_no_bare_read_text_calls(self) -> None:
        """commands/add.py must not contain bare .read_text() calls (no encoding arg)."""
        bare = bare_text_io_calls(_ADD_PY)
        read_bare = [b for b in bare if "read_text" in b[1]]
        assert read_bare == [], (
            f"commands/add.py has bare read_text() calls without encoding=: {read_bare}. "
            "Add encoding='utf-8' to every callsite (AC-12 / FR-38)."
        )

    def test_no_bare_write_text_calls(self) -> None:
        """commands/add.py must not contain bare .write_text() calls (no encoding arg)."""
        bare = bare_text_io_calls(_ADD_PY)
        write_bare = [b for b in bare if "write_text" in b[1]]
        assert write_bare == [], (
            f"commands/add.py has bare write_text() calls without encoding=: {write_bare}. "
            "Add encoding='utf-8' to every callsite (AC-12 / FR-38)."
        )
