"""Unit tests for the kanon why closest-match suggester.

Covers:
- Typo in source name within threshold -> source name in suggestion list
- Typo in project URL within threshold -> URL in suggestion list
- Typo in XML path within threshold -> XML path in suggestion list
- No candidate within threshold -> empty suggestion list
- More than 3 candidates within threshold -> exactly 3 returned, sorted ascending
- Ties broken by lexicographic sort of candidate value (deterministic)
- Env-var thresholds (KANON_WHY_SUGGEST_MAX_DISTANCE, KANON_WHY_SUGGEST_TOP_N) respected

AC-TEST-002
"""

from __future__ import annotations

import pytest

from kanon_cli.commands.why import (
    ChainNode,
    ResolvedTree,
    _build_suggestion_universe,
    _suggest_closest_matches,
)


def _make_source_node(name: str, sha: str = "a" * 40) -> ChainNode:
    return ChainNode(kind="source", name=name, ref=None, sha=sha, url="https://github.com/org/catalog")


def _make_include_node(name: str, path_in_repo: str, sha: str = "c" * 40) -> ChainNode:
    return ChainNode(kind="include", name=name, ref=path_in_repo, sha=sha, url=None)


def _make_project_node(name: str, url: str, sha: str = "b" * 40) -> ChainNode:
    from kanon_cli.core.url import canonicalize_repo_url

    return ChainNode(
        kind="project",
        name=name,
        ref=None,
        sha=sha,
        url=url,
        canonical_url=canonicalize_repo_url(url),
    )


def _make_tree(
    source_name: str = "foo",
    include_path: str | None = None,
    project_url: str = "https://github.com/org/bar",
) -> ResolvedTree:
    """Build a minimal tree for testing the suggester."""
    source = _make_source_node(source_name)
    project = _make_project_node("bar", project_url)
    if include_path:
        include = _make_include_node("inc", include_path)
        include.children = [project]
        source.children = [include]
    else:
        source.children = [project]
    return ResolvedTree(sources=[source])


@pytest.mark.unit
class TestSuggestClosestMatchesBasic:
    """Basic signature and behaviour tests for _suggest_closest_matches."""

    def test_returns_list(self) -> None:
        """_suggest_closest_matches always returns a list."""
        universe = ["foo", "bar", "baz"]
        result = _suggest_closest_matches("fooo", universe, max_distance=3, top_n=3)
        assert isinstance(result, list)

    def test_exact_match_is_at_distance_zero(self) -> None:
        """The exact argument itself has distance 0 and is always first in the list."""
        universe = ["foo", "bar", "baz"]
        result = _suggest_closest_matches("foo", universe, max_distance=3, top_n=3)
        assert result[0] == "foo"

    def test_empty_universe_returns_empty(self) -> None:
        """Empty universe always returns an empty list."""
        result = _suggest_closest_matches("fooo", [], max_distance=3, top_n=3)
        assert result == []

    def test_no_candidate_within_threshold_returns_empty(self) -> None:
        """When no candidate is within max_distance, the list is empty."""

        universe = ["foo", "bar", "baz"]
        result = _suggest_closest_matches("xyzzy", universe, max_distance=3, top_n=3)
        assert result == []

    def test_exactly_at_threshold_is_included(self) -> None:
        """A candidate at exactly max_distance is included."""

        universe = ["foo"]
        result = _suggest_closest_matches("fooo", universe, max_distance=1, top_n=3)
        assert "foo" in result

    def test_beyond_threshold_excluded(self) -> None:
        """A candidate one step beyond the threshold is excluded."""

        universe = ["foo"]
        result = _suggest_closest_matches("fooo", universe, max_distance=0, top_n=3)
        assert result == []

    def test_top_n_caps_results(self) -> None:
        """Results are capped to top_n even when more candidates are within threshold."""

        universe = ["foo", "fob", "foc", "fod", "foe"]
        result = _suggest_closest_matches("foa", universe, max_distance=1, top_n=3)
        assert len(result) == 3

    def test_sorted_ascending_by_distance(self) -> None:
        """Results are sorted ascending by edit distance."""

        universe = ["fooooo", "foooo", "fooo"]
        result = _suggest_closest_matches("foo", universe, max_distance=3, top_n=3)

        assert result == ["fooo", "foooo", "fooooo"]

    def test_tie_broken_by_lexicographic_order(self) -> None:
        """Candidates at the same distance are sorted lexicographically (deterministic)."""

        universe = ["coo", "aoo", "boo"]
        result = _suggest_closest_matches("foo", universe, max_distance=1, top_n=3)

        assert result == ["aoo", "boo", "coo"]


@pytest.mark.unit
class TestSuggestByCategory:
    """Tests asserting that source names, URLs, and XML paths all appear in universe."""

    def test_typo_in_source_name_suggests_source(self) -> None:
        """One-char typo in source name -> source name is in suggestion list."""

        universe = ["foo", "https://github.com/org/bar", "repo-specs/inc.xml"]
        result = _suggest_closest_matches("fooo", universe, max_distance=3, top_n=3)
        assert "foo" in result

    def test_typo_in_url_suggests_url(self) -> None:
        """One-char typo in project URL -> URL is in suggestion list."""
        universe = ["foo", "https://github.com/org/bar", "repo-specs/inc.xml"]

        result = _suggest_closest_matches("https://github.com/org/barr", universe, max_distance=3, top_n=3)
        assert "https://github.com/org/bar" in result

    def test_typo_in_xml_path_suggests_xml_path(self) -> None:
        """One-char typo in XML path -> XML path is in suggestion list."""
        universe = ["foo", "https://github.com/org/bar", "repo-specs/inc.xml"]

        result = _suggest_closest_matches("repo-specs/incc.xml", universe, max_distance=3, top_n=3)
        assert "repo-specs/inc.xml" in result


@pytest.mark.unit
@pytest.mark.parametrize(
    "argument, universe, max_distance, top_n, expected_count",
    [
        ("foa", ["foo", "fob", "foc", "fod", "foe"], 1, 3, 3),
        ("foa", ["foo", "fob", "xyzzy"], 1, 3, 2),
        ("foa", ["foo", "fob", "foc"], 1, 1, 1),
        ("foa", ["foo", "fob", "foc"], 1, 5, 3),
    ],
)
class TestSuggestTopN:
    """Parametrized tests verifying the top_n cap and result count."""

    def test_result_count(
        self,
        argument: str,
        universe: list[str],
        max_distance: int,
        top_n: int,
        expected_count: int,
    ) -> None:
        """Result count is min(qualifying, top_n)."""
        result = _suggest_closest_matches(argument, universe, max_distance=max_distance, top_n=top_n)
        assert len(result) == expected_count


@pytest.mark.unit
class TestSuggestEnvVarThresholds:
    """Tests that env-var-driven thresholds affect suggester output."""

    def test_max_distance_zero_excludes_all_except_exact(self) -> None:
        """max_distance=0 only includes exact matches."""
        universe = ["foo", "bar", "baz"]

        result = _suggest_closest_matches("fooo", universe, max_distance=0, top_n=3)
        assert result == []

    def test_max_distance_custom_value_respects_threshold(self) -> None:
        """max_distance=2 includes candidates at distance 1 and 2 but not 3."""
        universe = ["foo", "fooo", "foooo"]

        result = _suggest_closest_matches("fo", universe, max_distance=2, top_n=10)
        assert "foo" in result
        assert "fooo" in result
        assert "foooo" not in result

    def test_top_n_of_one_returns_single_best(self) -> None:
        """top_n=1 returns exactly the single closest match."""
        universe = ["foo", "fob", "foc"]
        result = _suggest_closest_matches("foa", universe, max_distance=1, top_n=1)
        assert len(result) == 1

        assert result[0] == "fob"


@pytest.mark.unit
class TestBuildSuggestionUniverse:
    """Direct tests for _build_suggestion_universe covering all ChainNode kinds."""

    def test_source_node_name_in_universe(self) -> None:
        """A source ChainNode's name appears in the candidate universe."""
        source = ChainNode(
            kind="source",
            name="my-catalog",
            ref=None,
            sha="a" * 40,
            url="https://github.com/org/catalog",
        )
        tree = ResolvedTree(sources=[source])
        universe = _build_suggestion_universe(tree)
        assert "my-catalog" in universe

    def test_include_node_ref_in_universe(self) -> None:
        """An include ChainNode with a non-None ref has its ref (XML path) in the universe."""
        include = ChainNode(
            kind="include",
            name="inc",
            ref="repo-specs/manifests/main.xml",
            sha="c" * 40,
            url=None,
        )
        source = ChainNode(
            kind="source",
            name="my-catalog",
            ref=None,
            sha="a" * 40,
            url="https://github.com/org/catalog",
        )
        source.children = [include]
        tree = ResolvedTree(sources=[source])
        universe = _build_suggestion_universe(tree)
        assert "repo-specs/manifests/main.xml" in universe

    def test_include_node_name_in_universe_ref_none_adds_no_path(self) -> None:
        """An include ChainNode contributes its name; a None ref adds no path entry."""
        include = ChainNode(
            kind="include",
            name="inc",
            ref=None,
            sha="c" * 40,
            url=None,
        )
        source = ChainNode(
            kind="source",
            name="my-catalog",
            ref=None,
            sha="a" * 40,
            url="https://github.com/org/catalog",
        )
        source.children = [include]
        tree = ResolvedTree(sources=[source])
        universe = _build_suggestion_universe(tree)

        assert "inc" in universe
        assert universe.count("inc") == 1
        assert None not in universe

    def test_project_node_canonical_url_in_universe(self) -> None:
        """A project ChainNode with a canonical_url has that URL in the universe."""
        from kanon_cli.core.url import canonicalize_repo_url

        raw_url = "https://github.com/org/myproject.git"
        canonical = canonicalize_repo_url(raw_url)
        project = ChainNode(
            kind="project",
            name="myproject",
            ref=None,
            sha="b" * 40,
            url=raw_url,
            canonical_url=canonical,
        )
        source = ChainNode(
            kind="source",
            name="my-catalog",
            ref=None,
            sha="a" * 40,
            url="https://github.com/org/catalog",
        )
        source.children = [project]
        tree = ResolvedTree(sources=[source])
        universe = _build_suggestion_universe(tree)
        assert canonical in universe

    def test_all_node_kinds_collected_in_nested_tree(self) -> None:
        """A tree with source -> include -> project collects all three string types."""
        from kanon_cli.core.url import canonicalize_repo_url

        raw_url = "https://github.com/org/proj.git"
        canonical = canonicalize_repo_url(raw_url)
        project = ChainNode(
            kind="project",
            name="proj",
            ref=None,
            sha="b" * 40,
            url=raw_url,
            canonical_url=canonical,
        )
        include = ChainNode(
            kind="include",
            name="inc",
            ref="specs/nested.xml",
            sha="c" * 40,
            url=None,
        )
        include.children = [project]
        source = ChainNode(
            kind="source",
            name="my-catalog",
            ref=None,
            sha="a" * 40,
            url="https://github.com/org/catalog",
        )
        source.children = [include]
        tree = ResolvedTree(sources=[source])
        universe = _build_suggestion_universe(tree)
        assert "my-catalog" in universe
        assert "specs/nested.xml" in universe
        assert canonical in universe

    def test_empty_tree_returns_empty_universe(self) -> None:
        """A tree with no sources returns an empty candidate universe."""
        tree = ResolvedTree(sources=[])
        universe = _build_suggestion_universe(tree)
        assert universe == []
