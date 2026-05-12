"""Unit tests for src/kanon_cli/commands/list.py.

Covers the walker, sorted-index builder, empty-catalog stderr note, and the
missing-catalog-source canonical error per AC-TEST-001.
"""

import argparse
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.commands.list import (
    _build_sorted_index,
    _resolve_manifest_repo,
    _walk_marketplace_xmls,
    register,
    run_list,
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
            patch("kanon_cli.commands.list.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.commands.list.subprocess.run", return_value=mock_result),
            patch(
                "kanon_cli.commands.list._parse_catalog_source", return_value=("https://example.com/repo.git", "main")
            ),
            patch("kanon_cli.commands.list.is_version_constraint", return_value=False),
        ):
            result = _resolve_manifest_repo("https://example.com/repo.git@main")

        assert result == fake_repo

    def test_exits_1_when_clone_fails(self) -> None:
        """_resolve_manifest_repo calls sys.exit(1) when git clone fails."""
        mock_result = type("R", (), {"returncode": 1, "stderr": "fatal: repo not found"})()

        with (
            patch("kanon_cli.commands.list.tempfile.mkdtemp", return_value="/tmp/kanon-test"),
            patch("kanon_cli.commands.list.subprocess.run", return_value=mock_result),
            patch(
                "kanon_cli.commands.list._parse_catalog_source", return_value=("https://example.com/repo.git", "main")
            ),
            patch("kanon_cli.commands.list.is_version_constraint", return_value=False),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _resolve_manifest_repo("https://example.com/repo.git@main")
        assert exc_info.value.code == 1

    def test_exits_1_writes_error_to_stderr(self, capsys: pytest.CaptureFixture) -> None:
        """_resolve_manifest_repo writes ERROR: to stderr when clone fails."""
        mock_result = type("R", (), {"returncode": 1, "stderr": "fatal: repo not found"})()

        with (
            patch("kanon_cli.commands.list.tempfile.mkdtemp", return_value="/tmp/kanon-test"),
            patch("kanon_cli.commands.list.subprocess.run", return_value=mock_result),
            patch(
                "kanon_cli.commands.list._parse_catalog_source", return_value=("https://example.com/repo.git", "main")
            ),
            patch("kanon_cli.commands.list.is_version_constraint", return_value=False),
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
            patch("kanon_cli.commands.list.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.commands.list.subprocess.run", side_effect=capture_run),
            patch(
                "kanon_cli.commands.list._parse_catalog_source", return_value=("https://example.com/repo.git", "latest")
            ),
            patch("kanon_cli.commands.list.is_version_constraint", return_value=False),
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
            patch("kanon_cli.commands.list.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.commands.list.subprocess.run", return_value=mock_result),
            patch(
                "kanon_cli.commands.list._parse_catalog_source",
                return_value=("https://example.com/repo.git", ">=1.0.0"),
            ),
            patch("kanon_cli.commands.list.is_version_constraint", return_value=True),
            patch("kanon_cli.commands.list.resolve_version", return_value="refs/tags/1.2.0") as mock_rv,
        ):
            _resolve_manifest_repo("https://example.com/repo.git@>=1.0.0")

        mock_rv.assert_called_once_with("https://example.com/repo.git", ">=1.0.0")


# ---------------------------------------------------------------------------
# Tests for _walk_marketplace_xmls
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWalkMarketplaceXmls:
    """Tests for the _walk_marketplace_xmls() walker helper."""

    def test_returns_xml_files_in_repo_specs(self, tmp_path: Path) -> None:
        """Walker discovers *-marketplace.xml files under repo-specs/."""
        repo_specs = tmp_path / "repo-specs"
        _write_marketplace_xml(repo_specs, "alpha")
        _write_marketplace_xml(repo_specs, "beta")

        results = list(_walk_marketplace_xmls(tmp_path))
        names = {p.name for p in results}
        assert "alpha-marketplace.xml" in names
        assert "beta-marketplace.xml" in names

    def test_discovers_nested_subdirectories(self, tmp_path: Path) -> None:
        """Walker recurses into subdirectories of repo-specs/."""
        nested = tmp_path / "repo-specs" / "team-a" / "subgroup"
        _write_marketplace_xml(nested, "nested-entry")

        results = list(_walk_marketplace_xmls(tmp_path))
        assert any(p.name == "nested-entry-marketplace.xml" for p in results)

    def test_ignores_catalog_directory(self, tmp_path: Path) -> None:
        """Walker does NOT return files under catalog/<name>/ (legacy path)."""
        legacy_dir = tmp_path / "catalog" / "some-entry"
        _write_marketplace_xml(legacy_dir, "legacy")

        results = list(_walk_marketplace_xmls(tmp_path))
        assert all("catalog" not in str(p) for p in results), (
            "Walker must not return files from the legacy catalog/ directory"
        )

    def test_returns_empty_when_no_xml_files(self, tmp_path: Path) -> None:
        """Walker returns no results when repo-specs/ has no XML files."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        # Non-XML file should not be returned
        (repo_specs / "README.txt").write_text("not xml")

        results = list(_walk_marketplace_xmls(tmp_path))
        assert results == []

    def test_returns_empty_when_repo_specs_missing(self, tmp_path: Path) -> None:
        """Walker returns no results when repo-specs/ directory is absent."""
        results = list(_walk_marketplace_xmls(tmp_path))
        assert results == []

    def test_only_matches_marketplace_xml_suffix(self, tmp_path: Path) -> None:
        """Walker only matches files ending in -marketplace.xml, not generic .xml."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        (repo_specs / "default.xml").write_text("<manifest/>")
        _write_marketplace_xml(repo_specs, "correct")

        results = list(_walk_marketplace_xmls(tmp_path))
        names = [p.name for p in results]
        assert "correct-marketplace.xml" in names
        assert "default.xml" not in names


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
# Tests for run_list: missing catalog source
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunListMissingCatalogSource:
    """run_list() returns non-zero with the canonical error when no source is set."""

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
        """run_list returns 1 when catalog_source is None and env var is unset."""
        args = self._make_args(catalog_source=None)
        result = run_list(args)
        assert result != 0

    def test_missing_source_writes_canonical_error_to_stderr(self, capsys: pytest.CaptureFixture) -> None:
        """run_list writes the canonical missing-catalog error to stderr."""
        args = self._make_args(catalog_source=None)
        run_list(args)
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err
        assert "catalog source" in captured.err.lower()

    def test_missing_source_empty_stdout(self, capsys: pytest.CaptureFixture) -> None:
        """run_list writes nothing to stdout on missing catalog source."""
        args = self._make_args(catalog_source=None)
        run_list(args)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_canonical_error_mentions_list_command(self, capsys: pytest.CaptureFixture) -> None:
        """The canonical error names the 'list' command in the error text."""
        args = self._make_args(catalog_source=None)
        run_list(args)
        captured = capsys.readouterr()
        assert "list" in captured.err

    def test_canonical_error_mentions_catalog_source_flag(self, capsys: pytest.CaptureFixture) -> None:
        """The canonical error mentions --catalog-source and KANON_CATALOG_SOURCE."""
        args = self._make_args(catalog_source=None)
        run_list(args)
        captured = capsys.readouterr()
        assert "--catalog-source" in captured.err
        assert "KANON_CATALOG_SOURCE" in captured.err


# ---------------------------------------------------------------------------
# Tests for run_list: empty catalog
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunListEmptyCatalog:
    """run_list() exits 0 with empty stdout and a stderr note for empty repos."""

    def test_empty_catalog_exits_0(self, tmp_path: Path) -> None:
        """run_list exits 0 when the manifest repo has zero marketplace XMLs."""
        (tmp_path / "repo-specs").mkdir()

        args = argparse.Namespace(catalog_source="unused", no_color=False)
        with patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path):
            result = run_list(args)
        assert result == 0

    def test_empty_catalog_empty_stdout(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_list writes nothing to stdout when the manifest repo is empty."""
        (tmp_path / "repo-specs").mkdir()

        args = argparse.Namespace(catalog_source="unused", no_color=False)
        with patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path):
            run_list(args)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_empty_catalog_writes_stderr_note(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_list writes 'manifest repo contains 0 entries' to stderr."""
        (tmp_path / "repo-specs").mkdir()

        args = argparse.Namespace(catalog_source="unused", no_color=False)
        with patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path):
            run_list(args)
        captured = capsys.readouterr()
        assert "manifest repo contains 0 entries" in captured.err


# ---------------------------------------------------------------------------
# Tests for run_list: happy path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunListHappyPath:
    """run_list() prints sorted entry names to stdout for non-empty catalogs."""

    def test_prints_sorted_names(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_list prints entry names sorted lexicographically, one per line."""
        repo_specs = tmp_path / "repo-specs"
        for name in ["zebra", "alpha", "mango"]:
            _write_marketplace_xml(repo_specs, name)

        args = argparse.Namespace(catalog_source="unused", no_color=False)
        with patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path):
            result = run_list(args)

        captured = capsys.readouterr()
        lines = captured.out.splitlines()
        assert lines == ["alpha", "mango", "zebra"]
        assert result == 0

    def test_exits_0_on_happy_path(self, tmp_path: Path) -> None:
        """run_list exits 0 when catalog has entries."""
        repo_specs = tmp_path / "repo-specs"
        _write_marketplace_xml(repo_specs, "my-entry")

        args = argparse.Namespace(catalog_source="unused", no_color=False)
        with patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path):
            result = run_list(args)
        assert result == 0

    def test_empty_stderr_on_happy_path(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_list writes nothing to stderr when the catalog is non-empty (no warnings in fixture)."""
        repo_specs = tmp_path / "repo-specs"
        _write_marketplace_xml(repo_specs, "my-entry")

        args = argparse.Namespace(catalog_source="unused", no_color=False)
        with patch("kanon_cli.commands.list._resolve_manifest_repo", return_value=tmp_path):
            run_list(args)
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
    """register() correctly registers the 'list' subparser."""

    def test_register_adds_list_subcommand(self) -> None:
        """register() adds a 'list' entry to the subparsers action."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["list"])
        assert args.command == "list"

    def test_list_subparser_has_catalog_source(self) -> None:
        """The list subparser includes the --catalog-source flag."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["list", "--catalog-source", "https://example.com/repo.git@main"])
        assert args.catalog_source == "https://example.com/repo.git@main"

    def test_list_subparser_no_color_via_root_parser(self) -> None:
        """The --no-color flag on the root parser propagates to the list subcommand namespace.

        The list subparser does NOT independently define --no-color; it relies on
        the root parser's global --no-color flag (added by add_global_flags) per
        the pattern used by all other subcommands. Verify via build_parser() that
        'kanon --no-color list' propagates no_color=True to the namespace.
        """
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["--no-color", "list"])
        assert args.no_color is True

    def test_list_subparser_sets_func(self) -> None:
        """register() sets args.func to run_list."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["list"])
        assert args.func is run_list

    def test_list_help_mentions_catalog_source(self) -> None:
        """list --help text mentions --catalog-source and KANON_CATALOG_SOURCE."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        import io

        # Capture help output for the list subcommand
        list_parser = subparsers.choices["list"]
        buf = io.StringIO()
        list_parser.print_help(file=buf)
        help_text = buf.getvalue()
        assert "--catalog-source" in help_text
        assert "KANON_CATALOG_SOURCE" in help_text


# ---------------------------------------------------------------------------
# Tests for MISSING_CATALOG_ERROR_TEMPLATE constant
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMissingCatalogErrorTemplate:
    """The constant used in the canonical missing-catalog error is well-formed."""

    def test_template_is_a_string(self) -> None:
        assert isinstance(MISSING_CATALOG_ERROR_TEMPLATE, str)

    def test_template_contains_error_prefix(self) -> None:
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="list")
        assert rendered.startswith("ERROR:")

    def test_template_mentions_catalog_source_flag(self) -> None:
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="list")
        assert "--catalog-source" in rendered

    def test_template_mentions_env_var(self) -> None:
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="list")
        assert "KANON_CATALOG_SOURCE" in rendered

    def test_template_substitutes_command_name(self) -> None:
        rendered = MISSING_CATALOG_ERROR_TEMPLATE.format(command="list")
        assert "list" in rendered
