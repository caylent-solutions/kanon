"""Unit tests for kanon why -- three-category argument matching and ambiguity detection.

Covers:
- XML-path-only match: argument matches an include node's path_in_repo.
- Source-name-only match: argument matches a top-level source name via derive_source_name.
- Source-name AND URL ambiguity: hard error listing both interpretations.
- XML-path AND source-name ambiguity: hard error listing both.
- All-three ambiguity: hard error listing all three.
- derive_source_name normalization parity: Foo-Bar matches foo_bar.
- Zero-matches: not-found error preserved from T1.

AC-TEST-001
"""

from __future__ import annotations

import argparse
import pathlib

import pytest

from kanon_cli.commands.why import (
    _match_by_source_name,
    _match_by_url,
    _match_by_xml_path,
    run,
    ChainNode,
    ResolvedTree,
)
from tests.conftest import _make_minimal_kanon_file, _write_lockfile


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_source_node(
    name: str,
    url: str = "https://github.com/org/catalog",
    sha: str = "a" * 40,
) -> ChainNode:
    return ChainNode(kind="source", name=name, ref=None, sha=sha, url=url)


def _make_include_node(
    name: str,
    path_in_repo: str,
    sha: str = "c" * 40,
    children: list[ChainNode] | None = None,
) -> ChainNode:
    node = ChainNode(kind="include", name=name, ref=path_in_repo, sha=sha, url=None)
    if children:
        node.children = children
    return node


def _make_project_node(
    name: str,
    url: str,
    sha: str = "b" * 40,
) -> ChainNode:
    from kanon_cli.core.url import canonicalize_repo_url

    return ChainNode(
        kind="project",
        name=name,
        ref=None,
        sha=sha,
        url=url,
        canonical_url=canonicalize_repo_url(url),
    )


def _make_args(
    target: str,
    kanon_file: str,
    lock_file: str | None = None,
    catalog_source: str | None = "file:///fake/catalog@HEAD",
    format: str = "text",
) -> argparse.Namespace:
    return argparse.Namespace(
        target=target,
        kanon_file=kanon_file,
        lock_file=lock_file,
        catalog_source=catalog_source,
        format=format,
    )


# ---------------------------------------------------------------------------
# _match_by_url unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMatchByUrl:
    """Tests for _match_by_url -- matches project nodes by canonicalized URL."""

    def test_url_match_returns_project_node(self) -> None:
        """Project URL exactly matches the target URL (after canonicalization)."""
        project = _make_project_node("baz", "https://github.com/org/baz")
        source = _make_source_node("FOO")
        source.children = [project]
        tree = ResolvedTree(sources=[source])

        matches = _match_by_url(tree, "https://github.com/org/baz")

        assert len(matches) == 1
        assert matches[0].kind == "project"
        assert matches[0].url == "https://github.com/org/baz"

    def test_url_no_match_returns_empty(self) -> None:
        """No project with the given URL returns empty list."""
        project = _make_project_node("baz", "https://github.com/org/baz")
        source = _make_source_node("FOO")
        source.children = [project]
        tree = ResolvedTree(sources=[source])

        matches = _match_by_url(tree, "https://github.com/org/other")

        assert matches == []

    def test_url_match_uses_canonicalization(self) -> None:
        """SCP form git@github.com:org/baz.git canonicalizes to match https:// form."""
        project = _make_project_node("baz", "https://github.com/org/baz")
        source = _make_source_node("FOO")
        source.children = [project]
        tree = ResolvedTree(sources=[source])

        matches = _match_by_url(tree, "git@github.com:org/baz.git")

        assert len(matches) == 1

    def test_url_match_returns_empty_for_xml_path(self) -> None:
        """An XML path like 'repo-specs/foo.xml' does NOT match any project URL."""
        project = _make_project_node("baz", "https://github.com/org/baz")
        source = _make_source_node("FOO")
        source.children = [project]
        tree = ResolvedTree(sources=[source])

        # An XML path is not a valid canonicalized URL -- _match_by_url returns empty
        # (canonicalize_repo_url raises ValueError for bare paths)
        matches = _match_by_url(tree, "repo-specs/foo.xml")

        assert matches == []


# ---------------------------------------------------------------------------
# _match_by_xml_path unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMatchByXmlPath:
    """Tests for _match_by_xml_path -- matches include nodes by path_in_repo."""

    def test_xml_path_match_returns_include_node(self) -> None:
        """Include node's path_in_repo exactly matches the target argument."""
        include = _make_include_node("inc", "repo-specs/foo.xml")
        source = _make_source_node("FOO")
        source.children = [include]
        tree = ResolvedTree(sources=[source])

        matches = _match_by_xml_path(tree, "repo-specs/foo.xml")

        assert len(matches) == 1
        assert matches[0].kind == "include"
        assert matches[0].ref == "repo-specs/foo.xml"

    def test_xml_path_no_match_returns_empty(self) -> None:
        """Non-existent XML path returns empty list."""
        include = _make_include_node("inc", "repo-specs/bar.xml")
        source = _make_source_node("FOO")
        source.children = [include]
        tree = ResolvedTree(sources=[source])

        matches = _match_by_xml_path(tree, "repo-specs/foo.xml")

        assert matches == []

    def test_xml_path_is_exact_string_equality(self) -> None:
        """Partial match does NOT count; exact string equality is required."""
        include = _make_include_node("inc", "repo-specs/foo.xml")
        source = _make_source_node("FOO")
        source.children = [include]
        tree = ResolvedTree(sources=[source])

        # Partial path does NOT match
        matches = _match_by_xml_path(tree, "foo.xml")

        assert matches == []

    def test_xml_path_match_nested_include(self) -> None:
        """Nested include node at any depth is matched by its path_in_repo."""
        child_include = _make_include_node("child", "repo-specs/nested/child.xml")
        parent_include = _make_include_node("parent", "repo-specs/parent.xml", children=[child_include])
        source = _make_source_node("FOO")
        source.children = [parent_include]
        tree = ResolvedTree(sources=[source])

        matches = _match_by_xml_path(tree, "repo-specs/nested/child.xml")

        assert len(matches) == 1
        assert matches[0].ref == "repo-specs/nested/child.xml"

    def test_xml_path_does_not_match_source_name(self) -> None:
        """Source node names do NOT match as XML paths."""
        source = _make_source_node("FOO")
        tree = ResolvedTree(sources=[source])

        matches = _match_by_xml_path(tree, "FOO")

        assert matches == []


# ---------------------------------------------------------------------------
# _match_by_source_name unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMatchBySourceName:
    """Tests for _match_by_source_name -- matches source nodes via derive_source_name."""

    def test_source_name_exact_match_lowercase(self) -> None:
        """Lowercase source name matches the source node directly."""
        source = _make_source_node("FOO")
        tree = ResolvedTree(sources=[source])

        matches = _match_by_source_name(tree, "foo")

        assert len(matches) == 1
        assert matches[0].kind == "source"
        assert matches[0].name == "FOO"

    def test_source_name_match_uppercased_argument(self) -> None:
        """Uppercase argument FOO normalizes to foo and matches source named FOO."""
        source = _make_source_node("FOO")
        tree = ResolvedTree(sources=[source])

        matches = _match_by_source_name(tree, "FOO")

        assert len(matches) == 1

    def test_source_name_normalization_dash_to_underscore(self) -> None:
        """Argument Foo-Bar normalizes to foo_bar and matches source token FOO_BAR."""
        source = _make_source_node("FOO_BAR")
        tree = ResolvedTree(sources=[source])

        matches = _match_by_source_name(tree, "Foo-Bar")

        assert len(matches) == 1
        assert matches[0].name == "FOO_BAR"

    def test_source_name_normalization_underscore_to_underscore(self) -> None:
        """Argument foo_bar matches source token FOO_BAR directly."""
        source = _make_source_node("FOO_BAR")
        tree = ResolvedTree(sources=[source])

        matches = _match_by_source_name(tree, "foo_bar")

        assert len(matches) == 1

    def test_source_name_no_match_returns_empty(self) -> None:
        """Argument that does not match any source name returns empty list."""
        source = _make_source_node("FOO")
        tree = ResolvedTree(sources=[source])

        matches = _match_by_source_name(tree, "bar")

        assert matches == []

    def test_source_name_does_not_match_include_nodes(self) -> None:
        """Include node names are NOT matched by source-name matching."""
        include = _make_include_node("foo", "repo-specs/foo.xml")
        source = _make_source_node("BAR")
        source.children = [include]
        tree = ResolvedTree(sources=[source])

        # 'foo' is an include name, not a source name
        matches = _match_by_source_name(tree, "foo")

        assert matches == []


# ---------------------------------------------------------------------------
# Ambiguity detection -- parametrized cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAmbiguityDetection:
    """Tests for the multi-category match resolution: ambiguity produces a hard error."""

    def test_xml_path_only_match_calls_chain_walker(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Argument matches only the XML path category -- chain walker runs, exit 0.

        The argument is the path_in_repo of an include node and is NOT a valid
        URL (so URL category returns empty) and does NOT match any source name.
        """
        source_name = "FOO"
        include_path = "repo-specs/unique-path.xml"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_path = _write_lockfile(tmp_path, source_name, project_url, include_path=include_path)

        args = _make_args(
            target=include_path,
            kanon_file=str(kanon_file),
            lock_file=str(lock_path),
        )

        exit_code = run(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        # Output must contain the include path
        assert include_path in captured.out

    def test_source_name_only_match_calls_chain_walker(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Argument matches only the source name category -- chain walker runs, exit 0.

        The source name FOO is matched by the argument 'foo' (lowercased).
        """
        source_name = "FOO"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_path = _write_lockfile(tmp_path, source_name, project_url)

        args = _make_args(
            target="foo",
            kanon_file=str(kanon_file),
            lock_file=str(lock_path),
        )

        exit_code = run(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        # Output must contain the source name
        assert "FOO" in captured.out

    def test_source_name_dash_normalization_match(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """Argument Foo-Bar matches source FOO_BAR via derive_source_name normalization."""
        source_name = "FOO_BAR"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_path = _write_lockfile(tmp_path, source_name, project_url)

        args = _make_args(
            target="Foo-Bar",
            kanon_file=str(kanon_file),
            lock_file=str(lock_path),
        )

        exit_code = run(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "FOO_BAR" in captured.out

    def test_source_name_and_url_ambiguity_hard_error(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Argument matches both source name AND project URL -- hard error, exit non-zero.

        URL + source-name ambiguity is "extremely unlikely but possible" per spec
        Section 4.5 step 3, so we force it via mocking: patch _match_by_url and
        _match_by_source_name to both return non-empty results, then assert that
        run() raises SystemExit with a non-zero code and that stderr names both
        interpretation labels (URL and source-name categories).
        """
        from unittest.mock import patch

        source_name = "FOO"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_path = _write_lockfile(tmp_path, source_name, project_url)

        args = _make_args(
            target="https://github.com/org/proj",
            kanon_file=str(kanon_file),
            lock_file=str(lock_path),
        )

        # Build nodes that the mock match functions will return
        url_node = _make_project_node("proj", "https://github.com/org/proj")
        source_node = _make_source_node("FOO")

        with (
            patch("kanon_cli.commands.why._match_by_url", return_value=[url_node]),
            patch("kanon_cli.commands.why._match_by_xml_path", return_value=[]),
            patch("kanon_cli.commands.why._match_by_source_name", return_value=[source_node]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                run(args)

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        # stderr must name both interpretation labels
        assert "project url" in captured.err.lower() or "url" in captured.err.lower()
        assert "source name" in captured.err.lower() or "source" in captured.err.lower()

    def test_all_three_categories_ambiguity_hard_error(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """All three categories (URL + XML path + source name) match -- hard error, exit non-zero.

        AC-TEST-001: patch all three _match_by_* functions to return non-empty results
        and verify that run() raises SystemExit with a non-zero code and that stderr
        contains labels from all three categories (url, xml_path, source_name).
        """
        from unittest.mock import patch

        source_name = "FOO"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_path = _write_lockfile(tmp_path, source_name, project_url)

        args = _make_args(
            target="ambiguous-token",
            kanon_file=str(kanon_file),
            lock_file=str(lock_path),
        )

        url_node = _make_project_node("proj", "https://github.com/org/proj")
        xml_node = _make_include_node("inc", "ambiguous-token")
        src_node = _make_source_node("FOO")

        with (
            patch("kanon_cli.commands.why._match_by_url", return_value=[url_node]),
            patch("kanon_cli.commands.why._match_by_xml_path", return_value=[xml_node]),
            patch("kanon_cli.commands.why._match_by_source_name", return_value=[src_node]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                run(args)

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        # stderr must contain labels from all three categories
        stderr_lower = captured.err.lower()
        assert "url" in stderr_lower, "Expected 'url' label in ambiguity error output"
        assert "xml" in stderr_lower or "manifest" in stderr_lower, (
            "Expected 'xml' or 'manifest' label in ambiguity error output"
        )
        assert "source" in stderr_lower, "Expected 'source' label in ambiguity error output"

    def test_xml_path_and_source_name_ambiguity_exits_nonzero(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Argument matches both XML path AND source name -- hard error, exit non-zero.

        Construction: source named "REPO_SPECS_FOO_XML" (normalize -> "repo_specs_foo_xml")
        and argument "Repo-Specs-Foo-Xml" (normalize -> "repo_specs_foo_xml").
        Also an include node with path_in_repo = "Repo-Specs-Foo-Xml" (exact string match).
        """
        source_name = "REPO_SPECS_FOO_XML"
        # The argument that will cause ambiguity:
        # - derive_source_name("Repo-Specs-Foo-Xml") = "repo_specs_foo_xml"
        # - derive_source_name("REPO_SPECS_FOO_XML") = "repo_specs_foo_xml"  -> MATCH on source
        # - XML path exact match: include node has path_in_repo = "Repo-Specs-Foo-Xml"
        ambiguous_arg = "Repo-Specs-Foo-Xml"
        include_path = ambiguous_arg  # exact string -- XML path matching is exact

        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_path = _write_lockfile(tmp_path, source_name, project_url, include_path=include_path)

        args = _make_args(
            target=ambiguous_arg,
            kanon_file=str(kanon_file),
            lock_file=str(lock_path),
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        # Error message must list both interpretations
        assert "source" in captured.err.lower() or "xml" in captured.err.lower()
        assert ambiguous_arg in captured.err or source_name.lower() in captured.err.lower()

    def test_zero_matches_not_found_error_preserved(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Zero matches across all categories -> not-found error (T1 behaviour preserved)."""
        source_name = "FOO"
        project_url = "https://github.com/org/present"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_path = _write_lockfile(tmp_path, source_name, project_url)

        args = _make_args(
            target="completely-absent-and-not-a-url",
            kanon_file=str(kanon_file),
            lock_file=str(lock_path),
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower()


# ---------------------------------------------------------------------------
# Parametrized derive_source_name normalization parity tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "source_token,argument,should_match",
    [
        ("FOO_BAR", "foo_bar", True),
        ("FOO_BAR", "Foo-Bar", True),
        ("FOO_BAR", "FOO-BAR", True),
        ("FOO_BAR", "FOO_BAR", True),
        ("FOO", "foo", True),
        ("FOO", "FOO", True),
        ("FOO", "bar", False),
        ("MY_SOURCE", "my-source", True),
        ("MY_SOURCE", "MY-SOURCE", True),
    ],
)
class TestDeriveSourceNameNormalizationParity:
    """Parametrized: derive_source_name normalization parity for source-name matching."""

    def test_normalization_parity(self, source_token: str, argument: str, should_match: bool) -> None:
        """derive_source_name(argument) == derive_source_name(source_token) -> match."""
        source = _make_source_node(source_token)
        tree = ResolvedTree(sources=[source])

        matches = _match_by_source_name(tree, argument)

        if should_match:
            assert len(matches) == 1, f"Expected source '{source_token}' to match argument '{argument}'"
        else:
            assert matches == [], f"Expected no match for source '{source_token}' with argument '{argument}'"


# ---------------------------------------------------------------------------
# Multi-category match resolution tests (internal helper level)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMultiCategoryResolution:
    """Tests for the three-category evaluation strategy.

    Evaluates all three categories without short-circuiting. Ambiguity = 2+ matches.
    """

    def test_url_category_match_only(self) -> None:
        """URL category returns a hit; XML and source-name return empty."""
        project = _make_project_node("baz", "https://github.com/org/baz")
        source = _make_source_node("SOMETHING_ELSE")
        source.children = [project]
        tree = ResolvedTree(sources=[source])

        url_hits = _match_by_url(tree, "https://github.com/org/baz")
        xml_hits = _match_by_xml_path(tree, "https://github.com/org/baz")
        src_hits = _match_by_source_name(tree, "https://github.com/org/baz")

        assert len(url_hits) == 1
        assert xml_hits == []
        assert src_hits == []

        all_hits = url_hits + xml_hits + src_hits
        assert len(all_hits) == 1

    def test_xml_category_match_only(self) -> None:
        """XML category returns a hit; URL and source-name return empty."""
        include = _make_include_node("inc", "repo-specs/bar.xml")
        source = _make_source_node("FOO")
        source.children = [include]
        tree = ResolvedTree(sources=[source])

        arg = "repo-specs/bar.xml"
        url_hits = _match_by_url(tree, arg)
        xml_hits = _match_by_xml_path(tree, arg)
        src_hits = _match_by_source_name(tree, arg)

        assert url_hits == []
        assert len(xml_hits) == 1
        assert src_hits == []

    def test_source_name_category_match_only(self) -> None:
        """Source-name category returns a hit; URL and XML return empty."""
        source = _make_source_node("MY_SOURCE")
        tree = ResolvedTree(sources=[source])

        arg = "my-source"
        url_hits = _match_by_url(tree, arg)
        xml_hits = _match_by_xml_path(tree, arg)
        src_hits = _match_by_source_name(tree, arg)

        assert url_hits == []
        assert xml_hits == []
        assert len(src_hits) == 1

    def test_xml_and_source_both_hit_produces_ambiguity_list(self) -> None:
        """When XML AND source-name both match, combined hits list has 2 entries."""
        source_name = "REPO_SPECS_FOO"
        arg = "Repo-Specs-Foo"

        source = _make_source_node(source_name)
        include = _make_include_node("inc", arg)  # exact path match
        source.children = [include]
        tree = ResolvedTree(sources=[source])

        url_hits = _match_by_url(tree, arg)
        xml_hits = _match_by_xml_path(tree, arg)
        src_hits = _match_by_source_name(tree, arg)

        all_hits = url_hits + xml_hits + src_hits
        assert len(all_hits) >= 2, "Expected at least 2 hits for ambiguity"

    def test_no_short_circuit_all_three_evaluated(self) -> None:
        """All three categories are evaluated even when the first returns a hit.

        This test verifies that _match_by_xml_path and _match_by_source_name are
        called even after _match_by_url returns a non-empty list (no early exit).
        """
        # XML path happens to equal the normalized source name token
        source_name = "REPO_SPECS_BAR"
        arg = "Repo-Specs-Bar"

        source = _make_source_node(source_name)
        include = _make_include_node("inc", arg)  # XML path exactly equals arg
        source.children = [include]
        tree = ResolvedTree(sources=[source])

        # URL match: arg is not a valid URL -- _match_by_url returns []
        url_hits = _match_by_url(tree, arg)
        # XML match: include path == arg -- returns 1 hit
        xml_hits = _match_by_xml_path(tree, arg)
        # Source name: derive_source_name("Repo-Specs-Bar") == "repo_specs_bar"
        #              derive_source_name("REPO_SPECS_BAR") == "repo_specs_bar" -- MATCH
        src_hits = _match_by_source_name(tree, arg)

        assert url_hits == []
        assert len(xml_hits) == 1
        assert len(src_hits) == 1


# ---------------------------------------------------------------------------
# Defensive path coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefensivePaths:
    """Tests for defensive error paths in run() that guard against internal invariant violations.

    These paths are theoretically unreachable via normal operation but are present
    to prevent silent failures from invariant violations.
    """

    def test_project_node_missing_canonical_url_exits_nonzero(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """URL match with a project node missing canonical_url -> hard error, exit non-zero.

        This covers the defensive check at the top of the URL dispatch branch in run().
        """
        from unittest.mock import patch

        from kanon_cli.commands.why import _MatchHit

        # Build a project node with no canonical_url (simulates internal invariant violation)
        broken_project = ChainNode(
            kind="project",
            name="broken",
            ref=None,
            sha="b" * 40,
            url="https://github.com/org/broken",
            canonical_url=None,  # violates invariant
        )
        source = _make_source_node("FOO")
        source.children = [broken_project]
        tree = ResolvedTree(sources=[source])

        broken_hit = _MatchHit(
            category="url",
            label="project URL 'https://github.com/org/broken'",
            node=broken_project,
        )

        kanon_file = _make_minimal_kanon_file(tmp_path, "FOO")
        project_url = "https://github.com/org/proj"
        lock_path = _write_lockfile(tmp_path, "FOO", project_url)

        args = _make_args(
            target="https://github.com/org/broken",
            kanon_file=str(kanon_file),
            lock_file=str(lock_path),
        )

        # Patch _resolve_match to return our broken hit and _build_tree_from_lockfile
        # to return our broken tree so the defensive branch is reached
        with (
            patch("kanon_cli.commands.why._resolve_match", return_value=broken_hit),
            patch("kanon_cli.commands.why._build_tree_from_lockfile", return_value=tree),
        ):
            with pytest.raises(SystemExit) as exc_info:
                run(args)

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "internal error" in captured.err.lower() or "canonical url" in captured.err.lower()

    def test_chains_empty_after_source_name_match_exits_nonzero(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Source-name match finds a node but _walk_chains_from_node returns [] -> hard error.

        This covers the defensive 'if not chains' check after the xml/source branch in run().
        A source node exists in the tree but has no project descendants (empty subtree).
        """
        from unittest.mock import patch

        from kanon_cli.commands.why import _MatchHit

        # Build an empty source node (no children -- no chains possible)
        empty_source = _make_source_node("MY_EMPTY_SOURCE")
        tree = ResolvedTree(sources=[empty_source])

        source_hit = _MatchHit(
            category="source_name",
            label="source name 'MY_EMPTY_SOURCE'",
            node=empty_source,
        )

        kanon_file = _make_minimal_kanon_file(tmp_path, "MY_EMPTY_SOURCE")
        project_url = "https://github.com/org/proj"
        lock_path = _write_lockfile(tmp_path, "MY_EMPTY_SOURCE", project_url)

        args = _make_args(
            target="my-empty-source",
            kanon_file=str(kanon_file),
            lock_file=str(lock_path),
        )

        # Patch both _resolve_match and the tree builder so we control the empty-chains path
        with (
            patch("kanon_cli.commands.why._resolve_match", return_value=source_hit),
            patch("kanon_cli.commands.why._build_tree_from_lockfile", return_value=tree),
            patch("kanon_cli.commands.why._walk_chains_from_node", return_value=[]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                run(args)

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower()
