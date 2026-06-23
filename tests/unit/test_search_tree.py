"""Unit tests for the --tree renderer in kanon search.

Covers:
- Tree row format: ``<kind> <name>@<resolved-spec> (<sha-12>)``.
- ASCII box-drawing characters: ``+--``, ``|  ``, ``\\--``.
- ``--max-depth N`` truncation (depth 0 = root only, depth 1 = one XML layer, etc.).
- Threshold-guardrail error message content and exit code.
- ``--tree`` / ``--all-versions`` mutual-exclusion check (hard error before catalog resolve).
- ``--no-filter-required`` bypasses the threshold guardrail.
- ``--max-depth 0`` counts as a filter and bypasses the threshold guardrail.

AC-TEST-001 (unit tests for tree renderer, max-depth, guardrail, exclusion check).
"""

import argparse
import io
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from kanon_cli.commands.search import (
    _parse_xml_includes_and_projects,
    _render_tree,
    _resolve_include_path,
    register,
    run_search,
)
from kanon_cli.constants import KANON_TREE_NO_FILTER_THRESHOLD


# ---------------------------------------------------------------------------
# Shared tree-node fixtures
# ---------------------------------------------------------------------------

_FULL_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>A test entry.</description>
        <version>{version}</version>
        <type>plugin</type>
        <owner-name>Test Owner</owner-name>
        <owner-email>owner@example.com</owner-email>
        <keywords>test</keywords>
      </catalog-metadata>
    </manifest>
""")

_XML_WITH_INCLUDE_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Entry with includes.</description>
        <version>{version}</version>
        <type>plugin</type>
        <owner-name>Test Owner</owner-name>
        <owner-email>owner@example.com</owner-email>
        <keywords>test</keywords>
      </catalog-metadata>
      <include name="{include_name}" />
      <remote name="origin" fetch="https://github.com/example" />
      <project name="{project_name}" remote="origin" revision="{project_revision}" />
    </manifest>
""")


def _write_marketplace_xml(directory: Path, name: str, version: str = "1.0.0") -> Path:
    """Write a minimal marketplace XML without includes."""
    directory.mkdir(parents=True, exist_ok=True)
    xml_path = directory / f"{name}-marketplace.xml"
    xml_path.write_text(_FULL_XML_TEMPLATE.format(name=name, version=version))
    return xml_path


def _write_marketplace_xml_with_include(
    directory: Path,
    name: str,
    version: str,
    include_name: str,
    project_name: str,
    project_revision: str,
) -> Path:
    """Write a marketplace XML that has an <include> and a <project>."""
    directory.mkdir(parents=True, exist_ok=True)
    xml_path = directory / f"{name}-marketplace.xml"
    xml_path.write_text(
        _XML_WITH_INCLUDE_TEMPLATE.format(
            name=name,
            version=version,
            include_name=include_name,
            project_name=project_name,
            project_revision=project_revision,
        )
    )
    return xml_path


# ---------------------------------------------------------------------------
# AC-FUNC-002: KANON_TREE_NO_FILTER_THRESHOLD constant
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKanonTreeNoFilterThresholdConstant:
    """KANON_TREE_NO_FILTER_THRESHOLD constant exists and has correct default."""

    def test_constant_is_int(self) -> None:
        """KANON_TREE_NO_FILTER_THRESHOLD is an int."""
        assert isinstance(KANON_TREE_NO_FILTER_THRESHOLD, int)

    def test_constant_default_value_is_20(self) -> None:
        """KANON_TREE_NO_FILTER_THRESHOLD default is 20."""
        assert KANON_TREE_NO_FILTER_THRESHOLD == 20

    def test_constant_is_positive(self) -> None:
        """KANON_TREE_NO_FILTER_THRESHOLD is a positive integer."""
        assert KANON_TREE_NO_FILTER_THRESHOLD > 0

    def test_env_override_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_TREE_NO_FILTER_THRESHOLD env var overrides the constant at import time.

        This test reloads the constants module with the env var set to verify the
        override mechanism is wired correctly.
        """
        import importlib
        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_TREE_NO_FILTER_THRESHOLD", "30")
        importlib.reload(constants)
        try:
            assert constants.KANON_TREE_NO_FILTER_THRESHOLD == 30
        finally:
            monkeypatch.delenv("KANON_TREE_NO_FILTER_THRESHOLD", raising=False)
            importlib.reload(constants)

    def test_env_override_invalid_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_TREE_NO_FILTER_THRESHOLD env var set to non-int raises ValueError."""
        import importlib
        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_TREE_NO_FILTER_THRESHOLD", "not-a-number")
        with pytest.raises((ValueError, SystemExit)):
            importlib.reload(constants)
        # Always restore to a clean state so subsequent tests are not affected
        monkeypatch.delenv("KANON_TREE_NO_FILTER_THRESHOLD", raising=False)
        importlib.reload(constants)


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-FUNC-007 / AC-FUNC-008: tree renderer format
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRenderTreeFormat:
    """_render_tree() outputs ASCII box-drawing and the correct node format."""

    def test_root_node_format_entry_kind(self, tmp_path: Path) -> None:
        """Root node is prefixed 'entry' and printed as 'entry <name>@<version> (<sha-12>)'."""
        repo_specs = tmp_path / "repo-specs"
        _write_marketplace_xml(repo_specs, "alpha", "2.0.0")

        lines = _render_tree(tmp_path, entry_name="alpha", max_depth=None)
        # Root line should start with 'entry alpha@'
        root_line = lines[0]
        assert root_line.startswith("entry alpha@"), f"Root node must start with 'entry alpha@'; got: {root_line!r}"

    def test_root_node_contains_sha(self, tmp_path: Path) -> None:
        """Root node contains a 12-character hex SHA in parentheses."""
        repo_specs = tmp_path / "repo-specs"
        _write_marketplace_xml(repo_specs, "beta", "1.2.3")

        lines = _render_tree(tmp_path, entry_name="beta", max_depth=None)
        root_line = lines[0]
        import re

        sha_match = re.search(r"\(([0-9a-f]{12})\)$", root_line)
        assert sha_match is not None, f"Root line must end with '(<sha-12>)' (12 hex chars); got: {root_line!r}"

    def test_no_emdash_in_output(self, tmp_path: Path) -> None:
        """Output contains no em-dash characters (U+2014). AC-FUNC-008, AC-FINAL-012."""
        repo_specs = tmp_path / "repo-specs"
        _write_marketplace_xml(repo_specs, "gamma", "1.0.0")

        lines = _render_tree(tmp_path, entry_name="gamma", max_depth=None)
        for line in lines:
            assert "\u2014" not in line, f"Em-dash (U+2014) found in rendered tree line: {line!r}"

    def test_xml_child_uses_ascii_box_drawing(self, tmp_path: Path) -> None:
        """XML child nodes use +-- or \\-- ASCII box-drawing prefix."""
        repo_specs = tmp_path / "repo-specs"
        included_xml = tmp_path / "included.xml"
        included_xml.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest />
        """)
        )
        _write_marketplace_xml_with_include(
            repo_specs,
            "pkg",
            "1.0.0",
            include_name="included.xml",
            project_name="my-project",
            project_revision="refs/heads/main",
        )

        lines = _render_tree(tmp_path, entry_name="pkg", max_depth=None)
        # At least one line after the root should use +-- or \--
        child_lines = lines[1:]
        assert any("+--" in ln or "\\--" in ln for ln in child_lines), (
            f"Expected '+--' or '\\--' in child lines; got: {child_lines!r}"
        )

    def test_xml_node_kind_prefix(self, tmp_path: Path) -> None:
        """XML-layer nodes are prefixed with 'xml'."""
        repo_specs = tmp_path / "repo-specs"
        included_xml = tmp_path / "included.xml"
        included_xml.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest />
        """)
        )
        _write_marketplace_xml_with_include(
            repo_specs,
            "pkg",
            "1.0.0",
            include_name="included.xml",
            project_name="my-project",
            project_revision="refs/heads/main",
        )

        lines = _render_tree(tmp_path, entry_name="pkg", max_depth=None)
        xml_lines = [ln for ln in lines if "xml" in ln and "+--" in ln or "xml" in ln and "\\--" in ln]
        assert len(xml_lines) >= 1, f"Expected at least one xml-prefixed child line; got lines: {lines!r}"

    def test_project_node_kind_prefix(self, tmp_path: Path) -> None:
        """Project-layer nodes are prefixed with 'project'."""
        repo_specs = tmp_path / "repo-specs"
        included_xml = tmp_path / "included.xml"
        included_xml.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest />
        """)
        )
        _write_marketplace_xml_with_include(
            repo_specs,
            "pkg",
            "1.0.0",
            include_name="included.xml",
            project_name="my-project",
            project_revision="refs/heads/main",
        )

        lines = _render_tree(tmp_path, entry_name="pkg", max_depth=None)
        project_lines = [ln for ln in lines if "project" in ln]
        assert len(project_lines) >= 1, f"Expected at least one project-prefixed line; got lines: {lines!r}"

    def test_max_depth_0_returns_only_root(self, tmp_path: Path) -> None:
        """max_depth=0 renders only the root 'entry' node -- no XML or project children."""
        repo_specs = tmp_path / "repo-specs"
        included_xml = tmp_path / "included.xml"
        included_xml.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest />
        """)
        )
        _write_marketplace_xml_with_include(
            repo_specs,
            "pkg",
            "1.0.0",
            include_name="included.xml",
            project_name="my-project",
            project_revision="refs/heads/main",
        )

        lines = _render_tree(tmp_path, entry_name="pkg", max_depth=0)
        assert len(lines) == 1, f"max_depth=0 should produce exactly 1 line (root only); got: {lines!r}"
        assert lines[0].startswith("entry pkg@"), (
            f"max_depth=0 root line should start with 'entry pkg@'; got: {lines[0]!r}"
        )

    def test_max_depth_1_shows_xml_but_not_project(self, tmp_path: Path) -> None:
        """max_depth=1 shows the catalog root and the XML layer but suppresses project nodes."""
        repo_specs = tmp_path / "repo-specs"
        included_xml = tmp_path / "included.xml"
        included_xml.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest />
        """)
        )
        _write_marketplace_xml_with_include(
            repo_specs,
            "mypkg",
            "1.0.0",
            include_name="included.xml",
            project_name="proj-a",
            project_revision="refs/heads/dev",
        )

        lines = _render_tree(tmp_path, entry_name="mypkg", max_depth=1)
        # XML nodes at depth 1 should appear; project nodes at depth 2 should not
        assert any("xml" in ln for ln in lines), f"max_depth=1 should show xml nodes; got lines: {lines!r}"
        assert not any("project" in ln for ln in lines), (
            f"max_depth=1 should suppress project nodes; got lines: {lines!r}"
        )

    def test_render_tree_returns_list_of_strings(self, tmp_path: Path) -> None:
        """_render_tree() returns a non-empty list of strings."""
        repo_specs = tmp_path / "repo-specs"
        _write_marketplace_xml(repo_specs, "entry-a", "3.0.0")

        lines = _render_tree(tmp_path, entry_name="entry-a", max_depth=None)
        assert isinstance(lines, list)
        assert len(lines) >= 1
        assert all(isinstance(ln, str) for ln in lines)


# ---------------------------------------------------------------------------
# AC-FUNC-004: Threshold guardrail error message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestThresholdGuardrail:
    """run_search() with --tree fires the threshold guardrail when catalog is too large."""

    def _make_large_catalog(self, tmp_path: Path, count: int) -> None:
        """Create ``count`` marketplace XML files in tmp_path/repo-specs/."""
        repo_specs = tmp_path / "repo-specs"
        for i in range(count):
            _write_marketplace_xml(repo_specs, f"entry-{i:03d}", "1.0.0")

    def _make_args(
        self,
        *,
        tree: bool = True,
        max_depth: int | None = None,
        no_filter_required: bool = False,
        all_versions: bool = False,
        catalog_source: str = "unused",
    ) -> argparse.Namespace:
        return argparse.Namespace(
            catalog_source=catalog_source,
            tree=tree,
            max_depth=max_depth,
            no_filter_required=no_filter_required,
            all_versions=all_versions,
            detail=False,
            no_color=False,
        )

    def test_guardrail_fires_when_over_threshold(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """With --tree and no filter, run_search exits non-zero when entries > threshold."""
        count = KANON_TREE_NO_FILTER_THRESHOLD + 1
        self._make_large_catalog(tmp_path, count)
        args = self._make_args()

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        assert result != 0, "Expected non-zero exit when guardrail fires"

    def test_guardrail_error_names_threshold(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Guardrail error message names the threshold value."""
        count = KANON_TREE_NO_FILTER_THRESHOLD + 1
        self._make_large_catalog(tmp_path, count)
        args = self._make_args()

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)

        captured = capsys.readouterr()
        assert str(KANON_TREE_NO_FILTER_THRESHOLD) in captured.err, (
            f"Guardrail message must name the threshold ({KANON_TREE_NO_FILTER_THRESHOLD}); got: {captured.err!r}"
        )

    def test_guardrail_error_names_actual_count(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Guardrail error message names the actual entry count."""
        count = KANON_TREE_NO_FILTER_THRESHOLD + 5
        self._make_large_catalog(tmp_path, count)
        args = self._make_args()

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)

        captured = capsys.readouterr()
        assert str(count) in captured.err, (
            f"Guardrail message must name the actual count ({count}); got: {captured.err!r}"
        )

    def test_guardrail_error_suggests_positional_substring(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Guardrail error suggests positional substring filter as a resolution path."""
        count = KANON_TREE_NO_FILTER_THRESHOLD + 1
        self._make_large_catalog(tmp_path, count)
        args = self._make_args()

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)

        captured = capsys.readouterr()
        # The error should mention some form of positional/substring filtering
        assert "substring" in captured.err.lower() or "<name>" in captured.err, (
            f"Guardrail message must suggest positional substring filter; got: {captured.err!r}"
        )

    def test_guardrail_error_suggests_regex(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Guardrail error suggests --regex as a resolution path."""
        count = KANON_TREE_NO_FILTER_THRESHOLD + 1
        self._make_large_catalog(tmp_path, count)
        args = self._make_args()

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)

        captured = capsys.readouterr()
        assert "--regex" in captured.err, f"Guardrail message must suggest --regex; got: {captured.err!r}"

    def test_guardrail_error_suggests_max_depth_0(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Guardrail error suggests --max-depth 0 as a resolution path."""
        count = KANON_TREE_NO_FILTER_THRESHOLD + 1
        self._make_large_catalog(tmp_path, count)
        args = self._make_args()

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)

        captured = capsys.readouterr()
        assert "--max-depth 0" in captured.err or "--max-depth" in captured.err, (
            f"Guardrail message must suggest --max-depth 0; got: {captured.err!r}"
        )

    def test_guardrail_error_suggests_no_filter_required(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Guardrail error suggests --no-filter-required as a resolution path."""
        count = KANON_TREE_NO_FILTER_THRESHOLD + 1
        self._make_large_catalog(tmp_path, count)
        args = self._make_args()

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)

        captured = capsys.readouterr()
        assert "--no-filter-required" in captured.err, (
            f"Guardrail message must suggest --no-filter-required; got: {captured.err!r}"
        )

    def test_guardrail_error_written_to_stderr(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Guardrail error is written to stderr (not stdout)."""
        count = KANON_TREE_NO_FILTER_THRESHOLD + 1
        self._make_large_catalog(tmp_path, count)
        args = self._make_args()

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)

        captured = capsys.readouterr()
        assert "ERROR:" in captured.err, (
            f"Guardrail error must start with ERROR: prefix in stderr; got: {captured.err!r}"
        )
        assert captured.out == "", f"Guardrail must produce no stdout output; got: {captured.out!r}"

    def test_guardrail_does_not_fire_at_threshold(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Guardrail does NOT fire when entry count equals threshold exactly."""
        count = KANON_TREE_NO_FILTER_THRESHOLD  # Equal, not over
        self._make_large_catalog(tmp_path, count)
        args = self._make_args()

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            with patch("kanon_cli.commands.search._render_tree", return_value=["entry fake@1.0.0 (aabbccddeeff)"]):
                result = run_search(args)

        assert result == 0, "Guardrail must NOT fire at exactly threshold entries"

    def test_guardrail_does_not_fire_without_tree_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Guardrail fires only with --tree; non-tree mode ignores entry count."""
        count = KANON_TREE_NO_FILTER_THRESHOLD + 10
        self._make_large_catalog(tmp_path, count)
        # No --tree flag
        args = argparse.Namespace(
            catalog_source="unused",
            tree=False,
            max_depth=None,
            no_filter_required=False,
            all_versions=False,
            detail=False,
            no_color=False,
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        assert result == 0, "Guardrail must not fire in non-tree mode even for large catalogs"

    def test_no_filter_required_bypasses_guardrail(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """--no-filter-required bypasses the threshold guardrail (AC-FUNC-004)."""
        count = KANON_TREE_NO_FILTER_THRESHOLD + 1
        self._make_large_catalog(tmp_path, count)
        args = self._make_args(no_filter_required=True)

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            with patch(
                "kanon_cli.commands.search._render_tree",
                return_value=["entry fake@1.0.0 (aabbccddeeff)"],
            ):
                result = run_search(args)

        assert result == 0, "--no-filter-required should bypass the guardrail"

    def test_max_depth_0_bypasses_guardrail(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """--max-depth 0 counts as a filter and bypasses the threshold guardrail (AC-FUNC-005)."""
        count = KANON_TREE_NO_FILTER_THRESHOLD + 1
        self._make_large_catalog(tmp_path, count)
        args = self._make_args(max_depth=0)

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            with patch(
                "kanon_cli.commands.search._render_tree",
                return_value=["entry fake@1.0.0 (aabbccddeeff)"],
            ):
                result = run_search(args)

        assert result == 0, "--max-depth 0 should bypass the guardrail as a valid filter"


# ---------------------------------------------------------------------------
# AC-FUNC-006: --tree --all-versions mutual exclusion
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTreeAllVersionsMutualExclusion:
    """--tree --all-versions is a hard error detected before catalog is resolved."""

    def test_tree_and_all_versions_is_hard_error(self, capsys: pytest.CaptureFixture) -> None:
        """run_search exits non-zero when both --tree and --all-versions are set."""
        args = argparse.Namespace(
            catalog_source="https://example.com/repo.git@main",
            tree=True,
            max_depth=None,
            no_filter_required=False,
            all_versions=True,
            detail=False,
            no_color=False,
        )

        # The conflict must be detected before any catalog resolution
        resolve_called = []

        def _record_resolve(src: str) -> None:
            resolve_called.append(src)
            raise AssertionError("_resolve_manifest_repo should NOT be called when flags conflict")

        with patch("kanon_cli.commands.search._resolve_manifest_repo", side_effect=_record_resolve):
            result = run_search(args)

        assert result != 0, "--tree --all-versions must produce a non-zero exit code"
        assert not resolve_called, "Conflict must be detected before _resolve_manifest_repo is called"

    def test_tree_and_all_versions_writes_error_to_stderr(self, capsys: pytest.CaptureFixture) -> None:
        """run_search writes an ERROR: message to stderr for --tree --all-versions conflict."""
        args = argparse.Namespace(
            catalog_source="https://example.com/repo.git@main",
            tree=True,
            max_depth=None,
            no_filter_required=False,
            all_versions=True,
            detail=False,
            no_color=False,
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", side_effect=AssertionError("not reached")):
            run_search(args)

        captured = capsys.readouterr()
        assert "ERROR:" in captured.err, (
            f"Expected ERROR: prefix in stderr for --tree --all-versions conflict; got: {captured.err!r}"
        )

    def test_tree_and_all_versions_mentions_both_flags(self, capsys: pytest.CaptureFixture) -> None:
        """The conflict error message mentions both --tree and the -A/--all flag."""
        args = argparse.Namespace(
            catalog_source="https://example.com/repo.git@main",
            tree=True,
            max_depth=None,
            no_filter_required=False,
            all_versions=True,
            detail=False,
            no_color=False,
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", side_effect=AssertionError("not reached")):
            run_search(args)

        captured = capsys.readouterr()
        assert "--tree" in captured.err, f"Conflict error must mention '--tree'; got: {captured.err!r}"
        assert "--all" in captured.err, f"Conflict error must mention the -A/--all flag; got: {captured.err!r}"

    def test_tree_without_all_versions_is_not_an_error(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """--tree alone (without --all-versions) is not a conflict error."""
        repo_specs = tmp_path / "repo-specs"
        _write_marketplace_xml(repo_specs, "my-entry", "1.0.0")

        args = argparse.Namespace(
            catalog_source="unused",
            tree=True,
            max_depth=None,
            no_filter_required=False,
            all_versions=False,
            detail=False,
            no_color=False,
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        assert result == 0, "--tree alone must not be an error"


# ---------------------------------------------------------------------------
# AC-FUNC-001: flags registered on the list subparser
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListFlagsRegistered:
    """--tree, --max-depth, and --no-filter-required are registered on the list subparser."""

    def _get_list_parser(self) -> argparse.ArgumentParser:
        """Return the list subparser."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        return subparsers.choices["search"]

    def test_tree_flag_registered(self) -> None:
        """list subparser accepts --tree flag."""
        list_parser = self._get_list_parser()
        args = list_parser.parse_args(["--tree"])
        assert args.tree is True

    def test_tree_flag_default_false(self) -> None:
        """--tree defaults to False when not passed."""
        list_parser = self._get_list_parser()
        args = list_parser.parse_args([])
        assert args.tree is False

    def test_max_depth_flag_registered(self) -> None:
        """list subparser accepts --max-depth N flag."""
        list_parser = self._get_list_parser()
        args = list_parser.parse_args(["--max-depth", "3"])
        assert args.max_depth == 3

    def test_max_depth_flag_default_none(self) -> None:
        """--max-depth defaults to None (unlimited) when not passed."""
        list_parser = self._get_list_parser()
        args = list_parser.parse_args([])
        assert args.max_depth is None

    def test_no_filter_required_flag_registered(self) -> None:
        """list subparser accepts --no-filter-required flag."""
        list_parser = self._get_list_parser()
        args = list_parser.parse_args(["--no-filter-required"])
        assert args.no_filter_required is True

    def test_no_filter_required_default_false(self) -> None:
        """--no-filter-required defaults to False when not passed."""
        list_parser = self._get_list_parser()
        args = list_parser.parse_args([])
        assert args.no_filter_required is False

    def test_all_flags_appear_in_help(self) -> None:
        """--tree, --max-depth, --no-filter-required appear in list --help text."""
        list_parser = self._get_list_parser()
        buf = io.StringIO()
        list_parser.print_help(file=buf)
        help_text = buf.getvalue()

        assert "--tree" in help_text, f"'--tree' not found in help: {help_text!r}"
        assert "--max-depth" in help_text, f"'--max-depth' not found in help: {help_text!r}"
        assert "--no-filter-required" in help_text, f"'--no-filter-required' not found in help: {help_text!r}"

    def test_help_mentions_threshold_guardrail(self) -> None:
        """list --help text mentions the threshold guardrail (AC-DOC-001)."""
        list_parser = self._get_list_parser()
        buf = io.StringIO()
        list_parser.print_help(file=buf)
        help_text = buf.getvalue()

        assert "threshold" in help_text.lower() or "KANON_TREE_NO_FILTER_THRESHOLD" in help_text, (
            f"Help text must mention threshold guardrail; got: {help_text!r}"
        )

    def test_help_mentions_four_resolution_paths(self) -> None:
        """list --help text lists the four filter resolution paths (AC-DOC-001)."""
        list_parser = self._get_list_parser()
        buf = io.StringIO()
        list_parser.print_help(file=buf)
        help_text = buf.getvalue()

        # The four paths: positional substring, --regex, --max-depth 0, --no-filter-required
        assert "--regex" in help_text, f"Help must mention --regex; got: {help_text!r}"
        assert "--max-depth" in help_text, f"Help must mention --max-depth; got: {help_text!r}"
        assert "--no-filter-required" in help_text, f"Help must mention --no-filter-required; got: {help_text!r}"


# ---------------------------------------------------------------------------
# AC-FUNC-003: tree renders without filter when at or below threshold
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTreeRendersWithoutFilterBelowThreshold:
    """--tree succeeds without a filter when catalog size <= threshold."""

    def test_below_threshold_exits_0(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search with --tree exits 0 when catalog has fewer entries than threshold."""
        repo_specs = tmp_path / "repo-specs"
        for i in range(3):  # well below threshold of 20
            _write_marketplace_xml(repo_specs, f"entry-{i}", "1.0.0")

        args = argparse.Namespace(
            catalog_source="unused",
            tree=True,
            max_depth=0,  # use max_depth=0 to avoid needing XML parsing for this check
            no_filter_required=False,
            all_versions=False,
            detail=False,
            no_color=False,
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        assert result == 0, f"Expected exit 0 for catalog with 3 entries (below threshold); got {result}"

    def test_at_threshold_exits_0(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search with --tree exits 0 when catalog has exactly threshold entries."""
        repo_specs = tmp_path / "repo-specs"
        for i in range(KANON_TREE_NO_FILTER_THRESHOLD):
            _write_marketplace_xml(repo_specs, f"entry-{i:02d}", "1.0.0")

        args = argparse.Namespace(
            catalog_source="unused",
            tree=True,
            max_depth=0,
            no_filter_required=False,
            all_versions=False,
            detail=False,
            no_color=False,
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        assert result == 0, (
            f"Expected exit 0 for catalog with exactly {KANON_TREE_NO_FILTER_THRESHOLD} entries; got {result}"
        )


# ---------------------------------------------------------------------------
# Coverage gap tests: edge paths in _parse_xml_includes_and_projects,
# _resolve_include_path, _render_tree, and run_search tree mode.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseXmlIncludesAndProjectsEdgePaths:
    """Edge paths in _parse_xml_includes_and_projects (coverage AC-FINAL-014)."""

    def test_malformed_xml_returns_empty(self, tmp_path: Path) -> None:
        """Malformed XML causes _parse_xml_includes_and_projects to return ([], [])."""
        bad_xml = tmp_path / "bad.xml"
        bad_xml.write_text("not xml at all <<<")

        includes, projects = _parse_xml_includes_and_projects(bad_xml)
        assert includes == []
        assert projects == []

    def test_none_root_returns_empty(self, tmp_path: Path) -> None:
        """When getroot() returns None (mocked), _parse_xml_includes_and_projects returns ([], [])."""
        valid_xml = tmp_path / "valid.xml"
        valid_xml.write_text("<manifest/>")

        # Mock the parsed tree to return None for getroot() -- defensive guard coverage.
        mock_tree = type("MockTree", (), {"getroot": lambda self: None})()
        with patch("kanon_cli.commands.search.ET.parse", return_value=mock_tree):
            includes, projects = _parse_xml_includes_and_projects(valid_xml)

        assert includes == []
        assert projects == []

    def test_include_without_name_attribute_ignored(self, tmp_path: Path) -> None:
        """<include> element without a 'name' attribute is skipped."""
        xml_path = tmp_path / "test.xml"
        xml_path.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <include />
            </manifest>
        """)
        )

        includes, _ = _parse_xml_includes_and_projects(xml_path)
        assert includes == []

    def test_project_without_matching_remote_uses_literal_remote_name(self, tmp_path: Path) -> None:
        """When <project remote="x"> has no matching <remote name="x">, fetch_url is 'x'."""
        xml_path = tmp_path / "test.xml"
        xml_path.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <project name="my-proj" remote="no-match" revision="main" />
            </manifest>
        """)
        )

        _, projects = _parse_xml_includes_and_projects(xml_path)
        assert len(projects) == 1
        proj_name, fetch_url, revision = projects[0]
        assert proj_name == "my-proj"
        assert fetch_url == "no-match"
        assert revision == "main"


@pytest.mark.unit
class TestResolveIncludePath:
    """Tests for _resolve_include_path (coverage AC-FINAL-014)."""

    def test_resolves_relative_to_xml_dir(self, tmp_path: Path) -> None:
        """_resolve_include_path finds file relative to xml_path's directory."""
        xml_dir = tmp_path / "repo-specs"
        xml_dir.mkdir()
        target = xml_dir / "child.xml"
        target.write_text("<manifest/>")
        xml_path = xml_dir / "parent.xml"
        xml_path.write_text("<manifest/>")

        result = _resolve_include_path("child.xml", xml_path, tmp_path)
        assert result == target

    def test_resolves_relative_to_manifest_root(self, tmp_path: Path) -> None:
        """_resolve_include_path falls back to manifest_root when not in xml dir."""
        xml_dir = tmp_path / "repo-specs"
        xml_dir.mkdir()
        xml_path = xml_dir / "parent.xml"
        xml_path.write_text("<manifest/>")
        # Target exists at manifest_root level, not in xml_dir
        target = tmp_path / "common.xml"
        target.write_text("<manifest/>")

        result = _resolve_include_path("common.xml", xml_path, tmp_path)
        assert result == target

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """_resolve_include_path returns None when the include file does not exist."""
        xml_path = tmp_path / "parent.xml"
        xml_path.write_text("<manifest/>")

        result = _resolve_include_path("does-not-exist.xml", xml_path, tmp_path)
        assert result is None


@pytest.mark.unit
class TestRenderTreeEdgePaths:
    """Edge paths in _render_tree (coverage AC-FINAL-014)."""

    def test_missing_include_target_renders_placeholder(self, tmp_path: Path) -> None:
        """When an <include> target cannot be resolved, a placeholder node is rendered."""
        repo_specs = tmp_path / "repo-specs"
        # Root XML references an include that doesn't exist
        repo_specs.mkdir(parents=True, exist_ok=True)
        xml_path = repo_specs / "pkg-marketplace.xml"
        xml_path.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>pkg</name>
                <display-name>Pkg Display</display-name>
                <description>Test.</description>
                <version>1.0.0</version>
                <type>plugin</type>
                <owner-name>Owner</owner-name>
                <owner-email>owner@example.com</owner-email>
                <keywords>test</keywords>
              </catalog-metadata>
              <include name="nonexistent.xml" />
            </manifest>
        """)
        )

        lines = _render_tree(tmp_path, entry_name="pkg", max_depth=None)
        placeholder_lines = [ln for ln in lines if "nonexistent.xml" in ln and "unknown" in ln]
        assert len(placeholder_lines) == 1, f"Expected one placeholder line for missing include; got: {lines!r}"

    def test_include_with_project_children_at_depth_2(self, tmp_path: Path) -> None:
        """Projects in an included XML appear at depth 2 under that XML node."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)

        # Create an included XML that has a project
        included = tmp_path / "child.xml"
        included.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <remote name="origin" fetch="https://github.com/example" />
              <project name="child-proj" remote="origin" revision="refs/heads/main" />
            </manifest>
        """)
        )

        xml_path = repo_specs / "mypkg-marketplace.xml"
        xml_path.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>mypkg</name>
                <display-name>MyPkg Display</display-name>
                <description>Test.</description>
                <version>2.0.0</version>
                <type>plugin</type>
                <owner-name>Owner</owner-name>
                <owner-email>owner@example.com</owner-email>
                <keywords>test</keywords>
              </catalog-metadata>
              <include name="child.xml" />
            </manifest>
        """)
        )

        lines = _render_tree(tmp_path, entry_name="mypkg", max_depth=None)
        project_lines = [ln for ln in lines if "project" in ln and "child-proj" in ln]
        assert len(project_lines) >= 1, f"Expected at least one project line for 'child-proj'; got lines: {lines!r}"

    def test_root_xml_projects_no_includes_appear_at_depth_1(self, tmp_path: Path) -> None:
        """Projects directly in root XML (no includes) appear as depth-1 children."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)
        xml_path = repo_specs / "direct-marketplace.xml"
        xml_path.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>direct</name>
                <display-name>Direct Display</display-name>
                <description>Test.</description>
                <version>1.0.0</version>
                <type>plugin</type>
                <owner-name>Owner</owner-name>
                <owner-email>owner@example.com</owner-email>
                <keywords>test</keywords>
              </catalog-metadata>
              <remote name="origin" fetch="https://github.com/example" />
              <project name="direct-proj" remote="origin" revision="main" />
            </manifest>
        """)
        )

        lines = _render_tree(tmp_path, entry_name="direct", max_depth=None)
        project_lines = [ln for ln in lines if "project" in ln and "direct-proj" in ln]
        assert len(project_lines) == 1, f"Expected one project line for 'direct-proj'; got lines: {lines!r}"

    def test_render_tree_raises_for_unknown_entry(self, tmp_path: Path) -> None:
        """_render_tree raises FileNotFoundError when entry_name is not in the catalog."""
        repo_specs = tmp_path / "repo-specs"
        _write_marketplace_xml(repo_specs, "existing-entry", "1.0.0")

        with pytest.raises(FileNotFoundError):
            _render_tree(tmp_path, entry_name="nonexistent-entry", max_depth=None)

    def test_render_tree_skips_malformed_xml_files_and_raises_for_entry(self, tmp_path: Path) -> None:
        """_render_tree skips malformed XML files when searching for entry_name.

        When a malformed XML is present alongside a valid marketplace XML,
        _render_tree should skip the malformed one and find the valid entry.
        """
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)
        # Write a valid marketplace XML for the target entry
        _write_marketplace_xml(repo_specs, "valid-entry", "1.0.0")
        # Write a malformed XML that will cause _parse_catalog_metadata to raise
        bad_xml = repo_specs / "bad-marketplace.xml"
        bad_xml.write_text("not xml at all <<<")

        # _render_tree must still find and render "valid-entry" despite the bad XML
        lines = _render_tree(tmp_path, entry_name="valid-entry", max_depth=0)
        assert lines[0].startswith("entry valid-entry@"), (
            f"Expected 'entry valid-entry@...' as root line; got: {lines[0]!r}"
        )

    def test_placeholder_only_includes_with_root_projects(self, tmp_path: Path) -> None:
        """When all includes are missing (placeholder only) and root XML has projects, projects render."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)
        xml_path = repo_specs / "ph-marketplace.xml"
        xml_path.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>ph</name>
                <display-name>PH Display</display-name>
                <description>Test.</description>
                <version>1.0.0</version>
                <type>plugin</type>
                <owner-name>Owner</owner-name>
                <owner-email>owner@example.com</owner-email>
                <keywords>test</keywords>
              </catalog-metadata>
              <include name="missing.xml" />
              <remote name="origin" fetch="https://github.com/example" />
              <project name="direct-proj" remote="origin" revision="main" />
            </manifest>
        """)
        )

        lines = _render_tree(tmp_path, entry_name="ph", max_depth=None)
        # Should have placeholder for missing.xml and a project line
        placeholder_lines = [ln for ln in lines if "missing.xml" in ln and "unknown" in ln]
        assert len(placeholder_lines) == 1, f"Expected placeholder for missing.xml; got: {lines!r}"
        project_lines = [ln for ln in lines if "project" in ln and "direct-proj" in ln]
        assert len(project_lines) == 1, f"Expected project line for direct-proj; got: {lines!r}"

    def test_multiple_includes_last_uses_backslash_prefix(self, tmp_path: Path) -> None:
        """The last include node uses the \\-- prefix (last-child indicator)."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir(parents=True, exist_ok=True)

        include_a = tmp_path / "include-a.xml"
        include_a.write_text("<manifest/>")
        include_b = tmp_path / "include-b.xml"
        include_b.write_text("<manifest/>")

        xml_path = repo_specs / "multi-marketplace.xml"
        xml_path.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <catalog-metadata>
                <name>multi</name>
                <display-name>Multi Display</display-name>
                <description>Test.</description>
                <version>1.0.0</version>
                <type>plugin</type>
                <owner-name>Owner</owner-name>
                <owner-email>owner@example.com</owner-email>
                <keywords>test</keywords>
              </catalog-metadata>
              <include name="include-a.xml" />
              <include name="include-b.xml" />
            </manifest>
        """)
        )

        lines = _render_tree(tmp_path, entry_name="multi", max_depth=None)
        # First include should use +--
        first_include_line = lines[1]
        assert first_include_line.startswith("+--"), f"First include should use '+--'; got: {first_include_line!r}"
        # Last include should use \\--
        last_include_line = lines[2]
        assert last_include_line.startswith("\\--"), f"Last include should use '\\--'; got: {last_include_line!r}"


@pytest.mark.unit
class TestRunListTreeEmptyCatalog:
    """run_search --tree with an empty catalog (AC-FINAL-014 coverage)."""

    def test_tree_empty_catalog_exits_0(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search --tree exits 0 for an empty catalog (0 entries)."""
        (tmp_path / "repo-specs").mkdir()

        args = argparse.Namespace(
            catalog_source="unused",
            tree=True,
            max_depth=None,
            no_filter_required=True,
            all_versions=False,
            detail=False,
            no_color=False,
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            result = run_search(args)

        assert result == 0

    def test_tree_empty_catalog_writes_note_to_stderr(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """run_search --tree writes the 0-entries note to stderr for an empty catalog."""
        (tmp_path / "repo-specs").mkdir()

        args = argparse.Namespace(
            catalog_source="unused",
            tree=True,
            max_depth=None,
            no_filter_required=True,
            all_versions=False,
            detail=False,
            no_color=False,
        )

        with patch("kanon_cli.commands.search._resolve_manifest_repo", return_value=tmp_path):
            run_search(args)

        captured = capsys.readouterr()
        assert "manifest repo contains 0 entries" in captured.err


# ---------------------------------------------------------------------------
# E24: Sibling-continuation connector assertions (DEFECT-005)
# ---------------------------------------------------------------------------

# Tree shapes parametrised for AC-FUNC-003.
# Each entry is a tuple of:
#   (shape_id, entry_name, sibling_configs)
# where sibling_configs is a list of (xml_stem, project_names) pairs.
_SIBLING_TREE_SHAPES = [
    (
        "two_siblings_two_children_each",
        "pkg-sibling",
        [
            ("include-a", ["proj-a1", "proj-a2"]),
            ("include-b", ["proj-b1", "proj-b2"]),
        ],
    ),
    (
        "three_siblings_one_child_each",
        "pkg-triple",
        [
            ("inc-x", ["proj-x1"]),
            ("inc-y", ["proj-y1"]),
            ("inc-z", ["proj-z1"]),
        ],
    ),
]


def _build_sibling_tree_fixture(
    tmp_path: Path,
    entry_name: str,
    sibling_configs: list[tuple[str, list[str]]],
) -> None:
    """Write a marketplace XML with multiple sibling include XMLs, each with projects.

    Each include XML is placed at ``tmp_path/<stem>.xml`` so that
    ``_resolve_include_path`` can locate it via the ``manifest_root`` fallback.

    Args:
        tmp_path: Pytest tmp_path fixture root.
        entry_name: Catalog entry name for the marketplace XML.
        sibling_configs: List of (xml_stem, project_names) pairs. Each pair
            produces one include XML file with the named projects.
    """
    repo_specs = tmp_path / "repo-specs"
    repo_specs.mkdir(parents=True, exist_ok=True)

    marketplace_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<manifest>",
        "  <catalog-metadata>",
        f"    <name>{entry_name}</name>",
        f"    <display-name>{entry_name} Display</display-name>",
        "    <description>Sibling-continuation test entry.</description>",
        "    <version>1.0.0</version>",
        "    <type>plugin</type>",
        "    <owner-name>Test Owner</owner-name>",
        "    <owner-email>owner@example.com</owner-email>",
        "    <keywords>test</keywords>",
        "  </catalog-metadata>",
    ]
    for stem, _ in sibling_configs:
        marketplace_lines.append(f'  <include name="{stem}.xml" />')
    marketplace_lines.append("</manifest>")
    marketplace_lines.append("")
    (repo_specs / f"{entry_name}-marketplace.xml").write_text("\n".join(marketplace_lines))

    for stem, projects in sibling_configs:
        include_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            "<manifest>",
        ]
        for proj in projects:
            include_lines.append('  <remote name="origin" fetch="https://github.com/example" />')
            include_lines.append(f'  <project name="{proj}" remote="origin" revision="refs/heads/main" />')
        include_lines.append("</manifest>")
        include_lines.append("")
        (tmp_path / f"{stem}.xml").write_text("\n".join(include_lines))


@pytest.mark.unit
@pytest.mark.parametrize(
    "shape_id,entry_name,sibling_configs",
    _SIBLING_TREE_SHAPES,
    ids=[s[0] for s in _SIBLING_TREE_SHAPES],
)
class TestTreeRendererSiblingContinuation:
    """_render_tree() uses correct connector sequences for siblings at each depth.

    DEFECT-005: multi-sibling entries produce wrong connectors. The non-last
    sibling include should use '+--' and its continuation column should be
    '|   ' (pipe + three spaces), not '|  ' (pipe + two spaces). The last
    sibling's continuation column must be '    ' (four spaces, no pipe).
    """

    def test_multi_sibling_at_depth_2_uses_pipe_continuation(
        self,
        tmp_path: Path,
        shape_id: str,
        entry_name: str,
        sibling_configs: list[tuple[str, list[str]]],
    ) -> None:
        """Non-last sibling produces '+--' and its children use '|   ' continuation.

        Expected output for two_siblings_two_children_each:
            entry pkg-sibling@1.0.0 (<sha>)
            +-- xml include-a@included (<sha>)
            |   +-- project proj-a1@refs/heads/main (<sha>)
            |   \\-- project proj-a2@refs/heads/main (<sha>)
            \\-- xml include-b@included (<sha>)
                +-- project proj-b1@refs/heads/main (<sha>)
                \\-- project proj-b2@refs/heads/main (<sha>)
        """
        _build_sibling_tree_fixture(tmp_path, entry_name, sibling_configs)
        lines = _render_tree(tmp_path, entry_name=entry_name, max_depth=None)

        # AC-FUNC-005: individual assert statements, each diagnosable independently.
        # Locate the first sibling include line.
        first_sibling_line = next(
            (ln for ln in lines if ln.startswith("+--") and "xml" in ln),
            None,
        )
        assert first_sibling_line is not None, (
            f"[shape={shape_id}] Expected a '+--' xml line for first sibling include; lines={lines!r}"
        )

        # AC-FUNC-002 assertion 1: non-last sibling uses '+--', not '\\--'.
        assert first_sibling_line.startswith("+--"), (
            f"[shape={shape_id}] First sibling include must use '+--' connector; got: {first_sibling_line!r}"
        )

        # Locate lines that are children of the first (non-last) sibling.
        # They must start with '|   ' (pipe + three spaces) continuation column.
        first_sibling_child_lines = [ln for ln in lines if ln.startswith("|   ")]
        assert len(first_sibling_child_lines) >= 1, (
            f"[shape={shape_id}] Expected child lines starting with '|   ' under first sibling include; lines={lines!r}"
        )

        # AC-FUNC-002 assertion 2: non-last child of non-last sibling uses '|   +--'.
        # Only applicable when the first sibling has more than one child; a single-child
        # sibling has no non-last child so only assertion 3 applies.
        first_sibling_child_count = len(sibling_configs[0][1])
        if first_sibling_child_count > 1:
            first_child = first_sibling_child_lines[0]
            assert "|   +--" in first_child, (
                f"[shape={shape_id}] First child of first sibling must contain '|   +--'; got: {first_child!r}"
            )

        # AC-FUNC-002 assertion 3: last child of non-last sibling uses '|   \\--'.
        last_child_of_first_sibling = first_sibling_child_lines[first_sibling_child_count - 1]
        assert "|   \\--" in last_child_of_first_sibling, (
            f"[shape={shape_id}] Last child of first sibling must contain '|   \\--'; "
            f"got: {last_child_of_first_sibling!r}"
        )

        # Locate the last sibling include line (uses '\\--').
        last_sibling_line = next(
            (ln for ln in lines if ln.startswith("\\--") and "xml" in ln),
            None,
        )
        assert last_sibling_line is not None, (
            f"[shape={shape_id}] Expected a '\\--' xml line for last sibling include; lines={lines!r}"
        )

        # AC-FUNC-002 assertion 4: last sibling uses '\\--'.
        assert last_sibling_line.startswith("\\--"), (
            f"[shape={shape_id}] Last sibling include must use '\\--' connector; got: {last_sibling_line!r}"
        )

        # Locate child lines of the last sibling.
        # They must start with '    ' (four spaces, no pipe).
        last_sibling_child_lines = [ln for ln in lines if ln.startswith("    ") and "project" in ln]
        assert len(last_sibling_child_lines) >= 1, (
            f"[shape={shape_id}] Expected child lines starting with '    ' under last sibling include; lines={lines!r}"
        )

        # AC-FUNC-002 assertion 5: non-last child of last sibling uses '    +--'.
        # Only applicable when the last sibling has more than one child; a single-child
        # sibling has no non-last child so only assertion 6 applies.
        last_sibling_child_count = len(sibling_configs[-1][1])
        if last_sibling_child_count > 1:
            first_child_of_last = last_sibling_child_lines[0]
            assert "    +--" in first_child_of_last, (
                f"[shape={shape_id}] First child of last sibling must contain '    +--'; got: {first_child_of_last!r}"
            )

        # AC-FUNC-002 assertion 6: last child of last sibling uses '    \\--'.
        last_child_of_last = last_sibling_child_lines[last_sibling_child_count - 1]
        assert "    \\--" in last_child_of_last, (
            f"[shape={shape_id}] Last child of last sibling must contain '    \\--'; got: {last_child_of_last!r}"
        )
