"""Unit tests for kanon_cli.completions.pep440_filter -- AC-TEST-002.

Covers: is_pep440_tag() and filter_pep440_tags() accept and reject sets.
"""

from __future__ import annotations

import pytest

from kanon_cli.completions.pep440_filter import filter_pep440_tags, is_pep440_tag


# ---------------------------------------------------------------------------
# is_pep440_tag
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsPep440Tag:
    """is_pep440_tag() accepts PEP 440 strings and rejects non-PEP-440 strings."""

    @pytest.mark.parametrize(
        ("ref_component", "expected"),
        [
            # Accept set -- all valid PEP 440 version shapes
            ("1.0.0", True),
            ("2.0.0", True),
            ("1.0.0a1", True),
            ("1.0.0.post1", True),
            ("1.0.0.dev1", True),
            ("1.0.0+local.1", True),
            # Calendar version (PEP 440 compatible)
            ("20231201", True),
            # Epoch
            ("1!1.0.0", True),
            # Prerelease shapes
            ("1.0.0b2", True),
            ("1.0.0rc3", True),
            # Reject set -- non-PEP-440 strings
            ("not-a-version", False),
            ("latest", False),
            # v3 is the last component of release/v3 -- packaging normalizes to "3" (valid PEP 440)
            ("v3", True),
            ("main", False),
            ("develop", False),
            ("feature-branch", False),
            ("", False),
        ],
        ids=[
            "simple-1.0.0",
            "simple-2.0.0",
            "prerelease-alpha",
            "post-release",
            "dev-release",
            "local-version",
            "calendar",
            "epoch",
            "prerelease-beta",
            "release-candidate",
            "not-a-version",
            "latest",
            "v3-normalizes-to-3-valid",
            "main-branch",
            "develop-branch",
            "feature-branch",
            "empty-string",
        ],
    )
    def test_is_pep440_tag(self, ref_component: str, expected: bool) -> None:
        assert is_pep440_tag(ref_component) is expected


# ---------------------------------------------------------------------------
# filter_pep440_tags
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFilterPep440Tags:
    """filter_pep440_tags() keeps PEP 440-valid tags and discards the rest."""

    def test_empty_list_returns_empty(self) -> None:
        """Empty input produces empty output."""
        assert filter_pep440_tags([]) == []

    def test_all_valid_tags_kept(self) -> None:
        """All PEP 440-valid tags are returned."""
        result = filter_pep440_tags(["1.0.0", "2.0.0", "1.0.0a1"])
        assert sorted(result) == ["1.0.0", "1.0.0a1", "2.0.0"]

    def test_invalid_tags_excluded(self) -> None:
        """Non-PEP-440 tags are excluded from the result."""
        result = filter_pep440_tags(["not-a-version", "latest"])
        assert result == []

    def test_mixed_list_keeps_survivors_only(self) -> None:
        """Mixed list: PEP 440-valid entries are kept, others are dropped."""
        result = filter_pep440_tags(["1.0.0", "not-a-version", "2.0.0", "latest"])
        assert sorted(result) == ["1.0.0", "2.0.0"]

    def test_ordering_of_survivors_preserved(self) -> None:
        """Relative ordering of survivors is preserved (not re-sorted)."""
        result = filter_pep440_tags(["2.0.0", "1.0.0", "3.0.0"])
        # Ordering from input is preserved
        assert result == ["2.0.0", "1.0.0", "3.0.0"]

    def test_last_path_component_filtering(self) -> None:
        """is_pep440_tag() operates on the full string passed as ref_component.

        (The last-component extraction for refs/tags/... happens in the caller;
        filter_pep440_tags receives already-extracted last components.)
        "v3" is the last component of refs/tags/release/v3 -- packaging normalizes
        it to "3" so it passes the filter (is_pep440_tag("v3") is True).
        """
        # v3 normalizes to 3 (valid PEP 440) via packaging; both pass the filter
        result = filter_pep440_tags(["v3", "1.0.0"])
        assert sorted(result) == ["1.0.0", "v3"]

    @pytest.mark.parametrize(
        "tag",
        [
            "1.0.0.post1",
            "1.0.0.dev1",
            "1.0.0+local.1",
            "20231201",
            "1!1.0.0",
            "1.0.0b2",
            "1.0.0rc3",
        ],
        ids=["post", "dev", "local", "calendar", "epoch", "beta", "rc"],
    )
    def test_all_pep440_shapes_accepted(self, tag: str) -> None:
        """Each PEP 440 version shape passes the filter individually."""
        result = filter_pep440_tags([tag])
        assert result == [tag], f"Expected [{tag!r}] but got {result!r}"
