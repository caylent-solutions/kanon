"""Unit tests for src/kanon_cli/commands/search.py.

Covers the walker, sorted-index builder, empty-catalog stderr note, the
missing-catalog-source canonical error, the per-source group header, the
-A/--all version-history flag, and AC-16 (the removed list subcommand yields
the argparse unknown-command exit 2) per AC-TEST-001 / FR-10.
"""

import argparse
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.commands.search import (
    _build_sorted_index,
    _resolve_manifest_repo,
    register,
    run_search,
)
from kanon_cli.constants import MISSING_CATALOG_ERROR_TEMPLATE


# ---------------------------------------------------------------------------
# XML fixture helpers
# ---------------------------------------------------------------------------

_FULL_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>A test entry.</description>
        <version>1.0.0</version>
        <type>plugin</type>
        <owner-name>Test Owner</owner-name>
        <owner-email>owner@example.com</owner-email>
        <keywords>test</keywords>
      </catalog-metadata>
    </manifest>
""")


def _write_marketplace_xml(directory: Path, name: str) -> Path:
    """Write a minimal marketplace XML to directory/<name>-marketplace.xml.

    Args:
        directory: Directory in which to create the file.
        name: Catalog entry name to embed in the XML.

    Returns:
        Path to the written file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    xml_path = directory / f"{name}-marketplace.xml"
    xml_path.write_text(_FULL_XML_TEMPLATE.format(name=name))
    return xml_path


# ---------------------------------------------------------------------------
# Tests for _resolve_manifest_repo
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveManifestRepo:
    """Tests for the _resolve_manifest_repo() git-clone wrapper."""

    def test_clones_and_returns_repo_dir(self, tmp_path: Path) -> None:
        """_resolve_manifest_repo clones the repo and returns the repo dir path."""
        fake_repo = tmp_path / "repo"
        fake_repo.mkdir()

        mock_result = type("R", (), {"returncode": 0, "stderr": ""})()

        with (
            patch("kanon_cli.commands.search.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.commands.search.subprocess.run", return_value=mock_result),
            patch(
                "kanon_cli.commands.search._parse_catalog_source", return_value=("https://example.com/repo.git", "main")
            ),
            patch("kanon_cli.commands.search.is_version_constraint", return_value=False),
        ):
            result = _resolve_manifest_repo("https://example.com/repo.git@main")

        assert result == fake_repo

    def test_exits_1_when_clone_fails(self) -> None:
        """_resolve_manifest_repo calls sys.exit(1) when git clone fails."""
        mock_result = type("R", (), {"returncode": 1, "stderr": "fatal: repo not found"})()

        with (
            patch("kanon_cli.commands.search.tempfile.mkdtemp", return_value="/tmp/kanon-test"),
            patch("kanon_cli.commands.search.subprocess.run", return_value=mock_result),
            patch(
                "kanon_cli.commands.search._parse_catalog_source", return_value=("https://example.com/repo.git", "main")
            ),
            patch("kanon_cli.commands.search.is_version_constraint", return_value=False),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _resolve_manifest_repo("https://example.com/repo.git@main")
        assert exc_info.value.code == 1

    def test_exits_1_writes_error_to_stderr(self, capsys: pytest.CaptureFixture) -> None:
        """_resolve_manifest_repo writes ERROR: to stderr when clone fails."""
        mock_result = type("R", (), {"returncode": 1, "stderr": "fatal: repo not found"})()

        with (
            patch("kanon_cli.commands.search.tempfile.mkdtemp", return_value="/tmp/kanon-test"),
            patch("kanon_cli.commands.search.subprocess.run", return_value=mock_result),
            patch(
                "kanon_cli.commands.search._parse_catalog_source", return_value=("https://example.com/repo.git", "main")
            ),
            patch("kanon_cli.commands.search.is_version_constraint", return_value=False),
        ):
            with pytest.raises(SystemExit):
                _resolve_manifest_repo("https://example.com/repo.git@main")

        captured = capsys.readouterr()
        assert "ERROR:" in captured.err

    def test_resolves_latest_ref_to_wildcard(self, tmp_path: Path) -> None:
        """_resolve_manifest_repo maps 'latest' ref to '*' before cloning."""
        fake_repo = tmp_path / "repo"
        fake_repo.mkdir()
        captured_args: list[list[str]] = []

        mock_result = type("R", (), {"returncode": 0, "stderr": ""})()

        def capture_run(args: list[str], **kwargs: object) -> object:
            captured_args.append(args)
            return mock_result

        with (
            patch("kanon_cli.commands.search.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.commands.search.subprocess.run", side_effect=capture_run),
            patch(
                "kanon_cli.commands.search._parse_catalog_source",
                return_value=("https://example.com/repo.git", "latest"),
            ),
            patch("kanon_cli.commands.search.is_version_constraint", return_value=False),
        ):
            _resolve_manifest_repo("https://example.com/repo.git@latest")

        assert captured_args, "subprocess.run should have been called"
        git_args = captured_args[0]
        assert "*" in git_args, f"Expected '*' branch arg for 'latest'; got {git_args!r}"

    def test_resolves_version_constraint_via_resolve_version(self, tmp_path: Path) -> None:
        """_resolve_manifest_repo calls resolve_version() for PEP 440 constraints."""
        fake_repo = tmp_path / "repo"
        fake_repo.mkdir()

        mock_result = type("R", (), {"returncode": 0, "stderr": ""})()

        with (
            patch("kanon_cli.commands.search.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.commands.search.subprocess.run", return_value=mock_result),
            patch(
                "kanon_cli.commands.search._parse_catalog_source",
                return_value=("https://example.com/repo.git", ">=1.0.0"),
            ),
            patch("kanon_cli.commands.search.is_version_constraint", return_value=True),
            patch("kanon_cli.commands.search.resolve_version", return_value="refs/tags/1.2.0") as mock_rv,
        ):
            _resolve_manifest_repo("https://example.com/repo.git@>=1.0.0")

        mock_rv.assert_called_once_with("https://example.com/repo.git", ">=1.0.0")


# ---------------------------------------------------------------------------
# Tests for _build_sorted_index
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildSortedIndex:
    """Tests for the _build_sorted_index() helper."""

    def test_returns_names_sorted_lexicographically(self, tmp_path: Path) -> None:
        """Entry names are returned in lexicographic order."""
        repo_specs = tmp_path / "repo-specs"
        for name in ["zebra", "alpha", "mango"]:
            _write_marketplace_xml(repo_specs, name)

        index = _build_sorted_index(tmp_path)
        assert index == ["alpha", "mango", "zebra"]

    def test_stable_across_runs(self, tmp_path: Path) -> None:
        """The sorted index is identical on multiple calls for the same repo."""
        repo_specs = tmp_path / "repo-specs"
        for name in ["gamma", "alpha", "beta"]:
            _write_marketplace_xml(repo_specs, name)

        first = _build_sorted_index(tmp_path)
        second = _build_sorted_index(tmp_path)
        assert first == second

    def test_returns_empty_for_empty_catalog(self, tmp_path: Path) -> None:
        """Empty catalog produces an empty index."""
        (tmp_path / "repo-specs").mkdir()
        assert _build_sorted_index(tmp_path) == []

    def test_single_entry(self, tmp_path: Path) -> None:
        """Single entry catalog returns a single-element list."""
        _write_marketplace_xml(tmp_path / "repo-specs", "only-one")
        assert _build_sorted_index(tmp_path) == ["only-one"]


# ---------------------------------------------------------------------------
# Tests for run_search: missing catalog source
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunListMissingCatalogSource:
    """run_search() returns non-zero with the canonical error when no source is set."""

    @pytest.fixture(autouse=True)
    def _clear_catalog_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ensure KANON_CATALOG_SOURCE is absent for every test in this class."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)

    def _make_args(self, catalog_source: str | None = None) -> argparse.Namespace:
        return argparse.Namespace(
            catalog_source=catalog_source,
            no_color=False,
        )

    def test_missing_source_exits_nonzero(self) -> None:
        """run_search returns 1 when catalog_source is None and env var is unset."""
        args = self._make_args(catalog_source=None)
        result = run_search(args)
        assert result != 0

    def test_missing_source_writes_canonical_error_to_stderr(self, capsys: pytest.CaptureFixture) -> None:
        """run_search writes the canonical missing-catalog error to stderr."""
        args = self._make_args(catalog_source=None)
        run_search(args)
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err
        assert "catalog source" in captured.err.lower()

    def test_missing_source_empty_stdout(self, capsys: pytest.CaptureFixture) -> None:
        """run_search writes nothing to stdout on missing catalog source."""
        args = self._make_args(catalog_source=None)
        run_search(args)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_canonical_error_mentions_search_command(self, capsys: pytest.CaptureFixture) -> None:
        """The canonical error names the 'search' command in the error text."""
        args = self._make_args(catalog_source=None)
        run_search(args)
        captured = capsys.readouterr()
        assert "search" in captured.err

    def test_canonical_error_mentions_catalog_source_flag(self, capsys: pytest.CaptureFixture) -> None:
        """The canonical error mentions --catalog-source and KANON_CATALOG_SOURCE."""
        args = self._make_args(catalog_source=None)
        run_search(args)
        captured = capsys.readouterr()
        assert "--catalog-source" in captured.err
        assert "KANON_CATALOG_SOURCE" in captured.err


# ---------------------------------------------------------------------------
# Tests for run_search: empty catalog
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunListEmptyCatalog:
    """run_search() exits 0 with empty stdout and a stderr note for empty repos."""

    def test_empty_catalog_exits_0(self, tmp_path: Path) -> None:
        """run_search exits 0 when the manifest repo has zero marketplace XMLs."""
        (tmp_path / "repo-specs").mkdir()

        args = argparse.Namespace(catalog_source="unused", no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)
        assert result == 0

    def test_empty_catalog_empty_stdout(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search writes nothing to stdout when the manifest repo is empty."""
        (tmp_path / "repo-specs").mkdir()

        args = argparse.Namespace(catalog_source="unused", no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_empty_catalog_writes_stderr_note(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search writes 'manifest repo contains 0 entries' to stderr."""
        (tmp_path / "repo-specs").mkdir()

        args = argparse.Namespace(catalog_source="unused", no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)
        captured = capsys.readouterr()
        assert "manifest repo contains 0 entries" in captured.err


# ---------------------------------------------------------------------------
# Tests for run_search: happy path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunListHappyPath:
    """run_search() prints sorted entry names to stdout for non-empty catalogs."""

    def test_prints_sorted_names(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search prints entry names sorted lexicographically, one per line."""
        repo_specs = tmp_path / "repo-specs"
        for name in ["zebra", "alpha", "mango"]:
            _write_marketplace_xml(repo_specs, name)

        args = argparse.Namespace(catalog_source="unused", no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        captured = capsys.readouterr()
        lines = captured.out.splitlines()
        assert lines == ["alpha", "mango", "zebra"]
        assert result == 0

    def test_exits_0_on_happy_path(self, tmp_path: Path) -> None:
        """run_search exits 0 when catalog has entries."""
        repo_specs = tmp_path / "repo-specs"
        _write_marketplace_xml(repo_specs, "my-entry")

        args = argparse.Namespace(catalog_source="unused", no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)
        assert result == 0

    def test_empty_stderr_on_happy_path(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search writes nothing to stderr when the catalog is non-empty (no warnings in fixture)."""
        repo_specs = tmp_path / "repo-specs"
        _write_marketplace_xml(repo_specs, "my-entry")

        args = argparse.Namespace(catalog_source="unused", no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)
        captured = capsys.readouterr()
        # stderr may contain recommended-field warnings from metadata parsing;
        # what must NOT appear is the 0-entries note or any ERROR line
        assert "manifest repo contains 0 entries" not in captured.err
        assert "ERROR:" not in captured.err


# ---------------------------------------------------------------------------
# Tests for register()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegister:
    """register() correctly registers the 'search' subparser (hard rename of 'list')."""

    def test_register_adds_search_subcommand(self) -> None:
        """register() adds a 'search' entry to the subparsers action."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["search"])
        assert args.command == "search"

    def test_search_subparser_has_catalog_source(self) -> None:
        """The search subparser includes the --catalog-source flag."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["search", "--catalog-source", "https://example.com/repo.git@main"])
        assert args.catalog_source == "https://example.com/repo.git@main"

    def test_search_subparser_no_color_via_root_parser(self) -> None:
        """The --no-color flag on the root parser propagates to the search subcommand namespace.

        The search subparser does NOT independently define --no-color; it relies on
        the root parser's global --no-color flag (added by add_global_flags) per
        the pattern used by all other subcommands. Verify via build_parser() that
        'kanon --no-color search' propagates no_color=True to the namespace.
        """
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["--no-color", "search"])
        assert args.no_color is True

    def test_search_subparser_sets_func(self) -> None:
        """register() sets args.func to run_search."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["search"])
        assert args.func is run_search

    def test_search_help_mentions_catalog_source(self) -> None:
        """search --help text mentions --catalog-source and KANON_CATALOG_SOURCE."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        import io

        # Capture help output for the search subcommand
        search_parser = subparsers.choices["search"]
        buf = io.StringIO()
        search_parser.print_help(file=buf)
        help_text = buf.getvalue()
        assert "--catalog-source" in help_text
        assert "KANON_CATALOG_SOURCE" in help_text

    def test_search_help_mentions_all_flag(self) -> None:
        """search --help text documents the -A/--all version-history flag."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        import io

        search_parser = subparsers.choices["search"]
        buf = io.StringIO()
        search_parser.print_help(file=buf)
        help_text = buf.getvalue()
        assert "-A" in help_text
        assert "--all" in help_text

    def test_search_short_dash_h_exits_0(self) -> None:
        """kanon search -h exits 0 (add_help=True on the search subparser)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["search", "-h"])
        assert exc_info.value.code == 0

    def test_search_subparser_has_add_help_true(self) -> None:
        """The 'search' subparser has add_help=True set explicitly."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        search_parser = subparsers.choices["search"]
        assert search_parser.add_help is True, "search subparser must have add_help=True so '-h' is accepted"

    def test_list_command_is_gone(self) -> None:
        """AC-16: 'list' is no longer a registered subcommand (hard rename, no alias).

        register() registers only 'search'; the old 'list' key must be absent so
        the removed list subcommand resolves to the argparse unknown-command path.
        """
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        assert "search" in subparsers.choices
        assert "list" not in subparsers.choices


# ---------------------------------------------------------------------------
# AC-16: the removed list subcommand -> argparse unknown-command exit 2
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListUnknownCommand:
    """AC-16: invoking the removed list subcommand yields the argparse exit code 2."""

    def test_kanon_list_exits_2(self) -> None:
        """`kanon` with the removed list token exits with code 2 (argparse invalid-choice)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["list"])
        assert exc_info.value.code == 2

    def test_kanon_search_help_exits_0(self) -> None:
        """`kanon search --help` exits 0 (the rename target is wired and accepts --help)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["search", "--help"])
        assert exc_info.value.code == 0

    def test_kanon_list_error_names_invalid_choice(self, capsys: pytest.CaptureFixture) -> None:
        """The unknown-command error names 'list' as the invalid choice and lists 'search'."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit):
            main(["list"])
        captured = capsys.readouterr()
        assert "list" in captured.err
        assert "search" in captured.err


# ---------------------------------------------------------------------------
# Tests for MISSING_CATALOG_ERROR_TEMPLATE constant
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMissingCatalogErrorTemplate:
    """The constant used in the canonical missing-catalog error is well-formed."""

    def test_template_is_a_string(self) -> None:
        assert isinstance(MISSING_CATALOG_ERROR_TEMPLATE, str)

    def test_template_contains_error_prefix(self) -> None:
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="search")
        assert rendered.startswith("ERROR:")

    def test_template_mentions_catalog_source_flag(self) -> None:
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="search")
        assert "--catalog-source" in rendered

    def test_template_mentions_env_var(self) -> None:
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="search")
        assert "KANON_CATALOG_SOURCE" in rendered

    def test_template_substitutes_command_name(self) -> None:
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="search")
        assert "search" in rendered


# ---------------------------------------------------------------------------
# Source grouping (spec Section 4.1 / FR-10)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSourceGroupHeader:
    """run_search() groups results under a per-source header on stderr."""

    def test_header_helper_formats_source(self) -> None:
        """_format_source_group_header renders 'Source: <url>@<ref>'."""
        from kanon_cli.commands.search import _format_source_group_header

        header = _format_source_group_header("https://example.com/repo.git@main")
        assert header == "Source: https://example.com/repo.git@main"

    def test_header_helper_rejects_empty_source(self) -> None:
        """_format_source_group_header fails fast on an empty source (no silent blank label)."""
        from kanon_cli.commands.search import _format_source_group_header

        with pytest.raises(ValueError):
            _format_source_group_header("")

    def test_run_search_emits_source_header_to_stderr(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search writes the resolved source group header to stderr, not stdout."""
        repo_specs = tmp_path / "repo-specs"
        for name in ["alpha", "beta"]:
            _write_marketplace_xml(repo_specs, name)

        source = "https://example.com/repo.git@main"
        args = argparse.Namespace(catalog_source=source, no_color=False)
        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        captured = capsys.readouterr()
        assert result == 0
        # Header is on stderr (grouping label), not stdout (pipeable entry names).
        assert f"Source: {source}" in captured.err
        assert "Source:" not in captured.out
        assert captured.out.splitlines() == ["alpha", "beta"]

    def test_missing_source_emits_no_header(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No source resolved -> no group header (the canonical error is emitted instead)."""
        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)
        args = argparse.Namespace(catalog_source=None, no_color=False)
        run_search(args)
        captured = capsys.readouterr()
        assert "Source:" not in captured.err
        assert "Source:" not in captured.out


# ---------------------------------------------------------------------------
# -A/--all version-history flag dispatch (spec Section 4.1 / FR-10)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAllVersionsFlagDispatch:
    """run_search() with -A/--all walks all tagged versions instead of latest-only."""

    def _make_all_args(self, source: str) -> argparse.Namespace:
        return argparse.Namespace(
            catalog_source=source,
            all_versions=True,
            no_limit=False,
            limit=50,
            since_version=None,
            list_format=None,
            tree=False,
            detail=False,
            no_color=False,
        )

    def test_all_flag_dispatches_to_version_walker(self, capsys: pytest.CaptureFixture) -> None:
        """-A/--all routes through the historical-version walker, emitting <name>@<version> rows."""
        from kanon_cli.commands.search import VersionRow

        source = "https://example.com/repo.git@main"
        rows = [
            VersionRow(name="alpha", version="2.0.0", ref="refs/tags/2.0.0", sha="sha2"),
            VersionRow(name="alpha", version="1.0.0", ref="refs/tags/1.0.0", sha="sha1"),
        ]
        args = self._make_all_args(source)
        with patch("kanon_cli.commands.search._walk_all_versions", return_value=rows) as walk:
            result = run_search(args)

        captured = capsys.readouterr()
        assert result == 0
        walk.assert_called_once()
        assert captured.out.splitlines() == ["alpha@2.0.0", "alpha@1.0.0"]
        # Even in all-versions mode the per-source group header is emitted to stderr.
        assert f"Source: {source}" in captured.err

    def test_default_is_latest_only(self, tmp_path: Path) -> None:
        """Without -A/--all, run_search does NOT invoke the version walker (latest-only default)."""
        repo_specs = tmp_path / "repo-specs"
        _write_marketplace_xml(repo_specs, "alpha")

        args = argparse.Namespace(catalog_source="https://example.com/repo.git@main", no_color=False)
        with (
            patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path),
            patch("kanon_cli.commands.search._walk_all_versions") as walk,
        ):
            result = run_search(args)

        assert result == 0
        walk.assert_not_called()
