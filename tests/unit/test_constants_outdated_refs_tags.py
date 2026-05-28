"""Unit tests for DEFECT-007 constants and normalization helpers.

Covers:
- REVISION_REF_PREFIXES, REVISION_CLASSIFICATION_VERSION, and
  REVISION_CLASSIFICATION_BRANCH are present in kanon_cli.constants and have
  the expected values (AC-FUNC-001).
- _normalize_revision_for_constraint: all three return-path contracts (version,
  branch, RevisionParseError) (AC-FUNC-002).
- _normalize_tag_revision_to_constraint: refs/tags/<version> -> refs/tags/==<version>
  conversion, pass-through for already-constraint-shaped revisions (AC-FUNC-002).
- No inline string literals for the classification tokens appear in outdated.py
  (AC-FUNC-001 indirect: token usage via imported names only).

Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
Section 4 E30 Change + Edge cases; CLAUDE.md NO HARD-CODED VALUES.
"""

from __future__ import annotations

import pytest

from kanon_cli.constants import (
    REVISION_CLASSIFICATION_BRANCH,
    REVISION_CLASSIFICATION_VERSION,
    REVISION_REF_PREFIX_HEADS,
    REVISION_REF_PREFIX_REMOTES,
    REVISION_REF_PREFIX_TAGS,
    REVISION_REF_PREFIXES,
)
from kanon_cli.commands.outdated import (
    RevisionParseError,
    _normalize_revision_for_constraint,
    _normalize_tag_revision_to_constraint,
)


# ---------------------------------------------------------------------------
# Constants shape tests (AC-FUNC-001)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRevisionConstants:
    """REVISION_REF_PREFIXES, REVISION_CLASSIFICATION_VERSION, and
    REVISION_CLASSIFICATION_BRANCH are present and have the expected shape."""

    def test_revision_ref_prefixes_is_tuple(self) -> None:
        assert isinstance(REVISION_REF_PREFIXES, tuple)

    def test_revision_ref_prefixes_contains_refs_tags(self) -> None:
        assert "refs/tags/" in REVISION_REF_PREFIXES

    def test_revision_ref_prefixes_contains_refs_heads(self) -> None:
        assert "refs/heads/" in REVISION_REF_PREFIXES

    def test_revision_ref_prefixes_contains_refs_remotes_origin(self) -> None:
        assert "refs/remotes/origin/" in REVISION_REF_PREFIXES

    def test_revision_classification_version_is_string(self) -> None:
        assert isinstance(REVISION_CLASSIFICATION_VERSION, str)
        assert REVISION_CLASSIFICATION_VERSION == "version"

    def test_revision_classification_branch_is_string(self) -> None:
        assert isinstance(REVISION_CLASSIFICATION_BRANCH, str)
        assert REVISION_CLASSIFICATION_BRANCH == "branch"

    def test_all_prefixes_end_with_slash(self) -> None:
        for prefix in REVISION_REF_PREFIXES:
            assert prefix.endswith("/"), f"prefix {prefix!r} must end with '/'"

    def test_refs_remotes_origin_ordered_before_refs_heads(self) -> None:
        """refs/remotes/origin/ must appear before refs/heads/ to ensure longer
        prefix is matched first, preventing refs/heads/ from matching
        refs/remotes/origin/main as 'remotes/origin/main'."""
        idx_remotes = REVISION_REF_PREFIXES.index("refs/remotes/origin/")
        idx_heads = REVISION_REF_PREFIXES.index("refs/heads/")
        assert idx_remotes < idx_heads

    def test_revision_ref_prefix_tags_constant_value(self) -> None:
        assert REVISION_REF_PREFIX_TAGS == "refs/tags/"

    def test_revision_ref_prefix_heads_constant_value(self) -> None:
        assert REVISION_REF_PREFIX_HEADS == "refs/heads/"

    def test_revision_ref_prefix_remotes_constant_value(self) -> None:
        assert REVISION_REF_PREFIX_REMOTES == "refs/remotes/origin/"

    def test_individual_prefix_constants_are_members_of_tuple(self) -> None:
        """The individual prefix constants must be present in REVISION_REF_PREFIXES."""
        assert REVISION_REF_PREFIX_TAGS in REVISION_REF_PREFIXES
        assert REVISION_REF_PREFIX_HEADS in REVISION_REF_PREFIXES
        assert REVISION_REF_PREFIX_REMOTES in REVISION_REF_PREFIXES


# ---------------------------------------------------------------------------
# _normalize_revision_for_constraint tests (AC-FUNC-002)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeRevisionForConstraint:
    """_normalize_revision_for_constraint returns the documented contract."""

    @pytest.mark.parametrize(
        "revision,expected_normalized",
        [
            # refs/tags/ + valid PEP 440 version -> (bare_version, "version")
            ("refs/tags/1.0.0", ("1.0.0", REVISION_CLASSIFICATION_VERSION)),
            ("refs/tags/2.3.4", ("2.3.4", REVISION_CLASSIFICATION_VERSION)),
            ("refs/tags/1.0.0a1", ("1.0.0a1", REVISION_CLASSIFICATION_VERSION)),
            ("refs/tags/1.0.0.post1", ("1.0.0.post1", REVISION_CLASSIFICATION_VERSION)),
            ("refs/tags/2026.4.1", ("2026.4.1", REVISION_CLASSIFICATION_VERSION)),
        ],
    )
    def test_refs_tags_version_returns_version_classification(
        self,
        revision: str,
        expected_normalized: tuple[str | None, str],
    ) -> None:
        result = _normalize_revision_for_constraint(revision)
        assert result == expected_normalized

    @pytest.mark.parametrize(
        "revision",
        [
            "refs/heads/main",
            "refs/heads/develop",
            "refs/heads/feature/my-feature",
            "refs/remotes/origin/main",
            "refs/remotes/origin/release/1.x",
        ],
    )
    def test_branch_shaped_ref_returns_branch_classification(
        self,
        revision: str,
    ) -> None:
        normalized, classification = _normalize_revision_for_constraint(revision)
        assert normalized is None
        assert classification == REVISION_CLASSIFICATION_BRANCH

    @pytest.mark.parametrize(
        "revision",
        [
            "main",
            "develop",
            "HEAD",
        ],
    )
    def test_plain_branch_name_returns_branch_classification(
        self,
        revision: str,
    ) -> None:
        """Plain branch names (no prefix, no slash) are pass-through branch tokens."""
        normalized, classification = _normalize_revision_for_constraint(revision)
        assert normalized is None
        assert classification == REVISION_CLASSIFICATION_BRANCH

    @pytest.mark.parametrize(
        "revision",
        [
            # refs/tags/ prefix but bare component is not a PEP 440 version
            # and not a branch-shaped prefix -- should raise RevisionParseError.
            "refs/tags/not-a-version",
            "refs/tags/feature/some-name",
        ],
    )
    def test_malformed_revision_raises_revision_parse_error(
        self,
        revision: str,
    ) -> None:
        with pytest.raises(RevisionParseError) as exc_info:
            _normalize_revision_for_constraint(revision)
        assert revision in str(exc_info.value)

    def test_revision_parse_error_has_revision_and_reason_attributes(self) -> None:
        rev = "refs/tags/not-a-version"
        with pytest.raises(RevisionParseError) as exc_info:
            _normalize_revision_for_constraint(rev)
        err = exc_info.value
        assert err.revision == rev
        assert err.reason

    def test_revision_parse_error_is_value_error(self) -> None:
        with pytest.raises(ValueError):
            _normalize_revision_for_constraint("refs/tags/not-a-version")

    def test_error_message_includes_remediation(self) -> None:
        with pytest.raises(RevisionParseError) as exc_info:
            _normalize_revision_for_constraint("refs/tags/not-a-version")
        assert "refs/..." in str(exc_info.value)


# ---------------------------------------------------------------------------
# _normalize_tag_revision_to_constraint tests (AC-FUNC-002)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeTagRevisionToConstraint:
    """_normalize_tag_revision_to_constraint converts refs/tags/<version> to
    refs/tags/==<version> and leaves other forms unchanged."""

    @pytest.mark.parametrize(
        "revision,expected",
        [
            # Bare version in refs/tags/ -> exact-match constraint
            ("refs/tags/1.0.0", "refs/tags/==1.0.0"),
            ("refs/tags/2.3.4", "refs/tags/==2.3.4"),
            ("refs/tags/1.0.0a1", "refs/tags/==1.0.0a1"),
            # Already a specifier -> unchanged
            ("refs/tags/~=1.0.0", "refs/tags/~=1.0.0"),
            ("refs/tags/>=1.0.0,<2.0.0", "refs/tags/>=1.0.0,<2.0.0"),
            ("refs/tags/==1.0.0", "refs/tags/==1.0.0"),
            # Wildcard -> unchanged
            ("refs/tags/*", "refs/tags/*"),
            # Plain constraint (no refs/tags/ prefix) -> unchanged
            ("~=1.0.0", "~=1.0.0"),
            (">=1.0.0", ">=1.0.0"),
        ],
    )
    def test_normalize_tag_revision(self, revision: str, expected: str) -> None:
        assert _normalize_tag_revision_to_constraint(revision) == expected

    def test_non_refs_tags_prefix_passed_through_unchanged(self) -> None:
        assert _normalize_tag_revision_to_constraint("refs/heads/main") == "refs/heads/main"

    def test_bare_constraint_without_prefix_unchanged(self) -> None:
        assert _normalize_tag_revision_to_constraint("1.0.0") == "1.0.0"
