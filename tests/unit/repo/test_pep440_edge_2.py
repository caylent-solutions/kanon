# Copyright (C) 2024 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for PEP 440 edge cases: pre-release, dev, post, and empty constraint.

Covers:
- AC-TEST-001: pre-release identifiers (alpha, beta, rc) resolve correctly.
- AC-TEST-002: dev identifier (1.0.0.dev1) resolves correctly.
- AC-TEST-003: post identifier (1.0.0.post1) resolves correctly.
- AC-TEST-004: empty constraint raises a clear ManifestInvalidRevisionError.
- AC-FUNC-001: All PEP 440 identifier types parse deterministically.

Spec references:
- PEP440-013: Pre-release versions (alpha, beta, rc) -- excluded by default
  unless the specifier itself references a pre-release.
- PEP440-014: Dev releases (N.N.N.devN) -- excluded by default unless
  the specifier references a dev release.
- PEP440-015: Post-releases (N.N.N.postN) -- included in >= constraints
  because post-releases are newer than the base release.
- PEP440-016: Empty constraint string is invalid and must raise a clear error.
"""

import pytest

from kanon_cli.repo import error, version_constraints

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_TAG_PREFIX = "refs/tags/project"

_PRERELEASE_TAGS = [
    f"{_TAG_PREFIX}/1.0.0a1",
    f"{_TAG_PREFIX}/1.0.0b1",
    f"{_TAG_PREFIX}/1.0.0rc1",
    f"{_TAG_PREFIX}/1.0.0",
    f"{_TAG_PREFIX}/1.1.0",
]

_DEV_TAGS = [
    f"{_TAG_PREFIX}/1.0.0.dev1",
    f"{_TAG_PREFIX}/1.0.0.dev2",
    f"{_TAG_PREFIX}/1.0.0",
]

_POST_TAGS = [
    f"{_TAG_PREFIX}/1.0.0",
    f"{_TAG_PREFIX}/1.0.0.post1",
    f"{_TAG_PREFIX}/1.0.0.post2",
]


# ---------------------------------------------------------------------------
# AC-TEST-001: Pre-release identifiers (alpha, beta, rc)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPreReleaseIdentifiers:
    """AC-TEST-001: pre-release identifiers (a, b, rc) parse and resolve correctly.

    PEP 440 defines three pre-release segment types: alpha (a), beta (b), and
    release-candidate (rc). By default, non-pre-release specifiers (>=1.0.0)
    exclude pre-release tags. When the specifier itself references a pre-release
    version (>=1.0.0a1), all pre-release tags satisfying the specifier are
    included in the candidate set.
    """

    @pytest.mark.parametrize(
        "revision,available_tags,expected_tag",
        [
            (
                f"{_TAG_PREFIX}/==1.0.0a1",
                _PRERELEASE_TAGS,
                f"{_TAG_PREFIX}/1.0.0a1",
            ),
            (
                f"{_TAG_PREFIX}/==1.0.0b1",
                _PRERELEASE_TAGS,
                f"{_TAG_PREFIX}/1.0.0b1",
            ),
            (
                f"{_TAG_PREFIX}/==1.0.0rc1",
                _PRERELEASE_TAGS,
                f"{_TAG_PREFIX}/1.0.0rc1",
            ),
            (
                f"{_TAG_PREFIX}/>=1.0.0a1",
                _PRERELEASE_TAGS,
                f"{_TAG_PREFIX}/1.1.0",
            ),
        ],
        ids=[
            "exact-alpha",
            "exact-beta",
            "exact-rc",
            "gte-from-alpha-picks-highest",
        ],
    )
    def test_prerelease_constraint_resolves_correctly(self, revision, available_tags, expected_tag):
        """Pre-release specifier resolves to the expected tag.

        Given: A constraint that references a pre-release version identifier.
        When: resolve_version_constraint() is called with candidate tags.
        Then: Returns the expected tag that satisfies the constraint.
        AC: AC-TEST-001, AC-FUNC-001.
        """
        result = version_constraints.resolve_version_constraint(revision, available_tags)
        assert result == expected_tag, (
            f"Pre-release constraint '{revision}' should resolve to '{expected_tag}', got '{result}'"
        )

    def test_non_prerelease_constraint_excludes_prerelease_tags(self):
        """A non-pre-release specifier excludes all pre-release candidate tags.

        Given: Tags include pre-release versions (a1, b1, rc1) and a stable release.
        When: resolve_version_constraint() is called with >=1.0.0 (no pre-release marker).
        Then: Pre-release tags (a1, b1, rc1) are excluded; only stable releases match.
        AC: AC-TEST-001, AC-FUNC-001.
        """
        # Only 1.0.0 and 1.1.0 are stable; a1, b1, rc1 must be excluded.
        result = version_constraints.resolve_version_constraint(
            f"{_TAG_PREFIX}/>=1.0.0",
            _PRERELEASE_TAGS,
        )
        assert result == f"{_TAG_PREFIX}/1.1.0", (
            f"Non-pre-release constraint must exclude alpha/beta/rc tags, got '{result}'"
        )
        assert result != f"{_TAG_PREFIX}/1.0.0rc1", "rc1 must not be selected by a non-pre-release constraint"
        assert result != f"{_TAG_PREFIX}/1.0.0b1", "b1 must not be selected by a non-pre-release constraint"
        assert result != f"{_TAG_PREFIX}/1.0.0a1", "a1 must not be selected by a non-pre-release constraint"

    @pytest.mark.parametrize(
        "revision",
        [
            f"{_TAG_PREFIX}/>=1.0.0a1",
            f"{_TAG_PREFIX}/==1.0.0rc1",
            f"{_TAG_PREFIX}/>=1.0.0b1",
        ],
        ids=["gte-alpha", "exact-rc", "gte-beta"],
    )
    def test_prerelease_revision_is_detected_as_version_constraint(self, revision):
        """Pre-release revision strings are recognised as PEP 440 version constraints.

        Given: A revision containing a PEP 440 operator followed by a pre-release version.
        When: is_version_constraint() is called.
        Then: Returns True.
        AC: AC-TEST-001, AC-FUNC-001.
        """
        assert version_constraints.is_version_constraint(revision) is True, (
            f"Pre-release revision '{revision}' must be detected as a version constraint"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Dev identifier (1.0.0.dev1)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDevIdentifier:
    """AC-TEST-002: dev identifier (N.N.N.devN) resolves correctly.

    PEP 440 dev releases are ordered before the corresponding release version.
    Dev releases are excluded by non-dev specifiers by default (same rule as
    pre-releases). A specifier that references a dev version includes dev
    candidates.
    """

    @pytest.mark.parametrize(
        "revision,available_tags,expected_tag",
        [
            (
                f"{_TAG_PREFIX}/==1.0.0.dev1",
                _DEV_TAGS,
                f"{_TAG_PREFIX}/1.0.0.dev1",
            ),
            (
                f"{_TAG_PREFIX}/==1.0.0.dev2",
                _DEV_TAGS,
                f"{_TAG_PREFIX}/1.0.0.dev2",
            ),
            (
                f"{_TAG_PREFIX}/>=1.0.0.dev0",
                _DEV_TAGS,
                f"{_TAG_PREFIX}/1.0.0",
            ),
        ],
        ids=[
            "exact-dev1",
            "exact-dev2",
            "gte-dev0-picks-stable",
        ],
    )
    def test_dev_constraint_resolves_correctly(self, revision, available_tags, expected_tag):
        """Dev specifier resolves to the expected tag.

        Given: A constraint that references a dev version identifier.
        When: resolve_version_constraint() is called with candidate tags.
        Then: Returns the expected tag that satisfies the constraint.
        AC: AC-TEST-002, AC-FUNC-001.
        """
        result = version_constraints.resolve_version_constraint(revision, available_tags)
        assert result == expected_tag, f"Dev constraint '{revision}' should resolve to '{expected_tag}', got '{result}'"

    def test_dev_revision_is_detected_as_version_constraint(self):
        """A dev revision string is recognised as a PEP 440 version constraint.

        Given: A revision containing == followed by a dev version.
        When: is_version_constraint() is called.
        Then: Returns True.
        AC: AC-TEST-002, AC-FUNC-001.
        """
        revision = f"{_TAG_PREFIX}/==1.0.0.dev1"
        assert version_constraints.is_version_constraint(revision) is True, (
            f"Dev revision '{revision}' must be detected as a version constraint"
        )

    def test_non_dev_constraint_excludes_dev_tags(self):
        """A non-dev specifier excludes dev releases from the candidate set.

        Given: Tags include a dev release (1.0.0.dev1) and a stable release (1.0.0).
        When: resolve_version_constraint() is called with >=1.0.0 (no dev marker).
        Then: The dev tag is excluded; only stable releases match.
        AC: AC-TEST-002, AC-FUNC-001.
        """
        result = version_constraints.resolve_version_constraint(
            f"{_TAG_PREFIX}/>=1.0.0",
            _DEV_TAGS,
        )
        assert result == f"{_TAG_PREFIX}/1.0.0", f"Non-dev constraint must exclude dev tags, got '{result}'"
        assert result != f"{_TAG_PREFIX}/1.0.0.dev1", "dev1 must not be selected by a non-dev constraint"
        assert result != f"{_TAG_PREFIX}/1.0.0.dev2", "dev2 must not be selected by a non-dev constraint"


# ---------------------------------------------------------------------------
# AC-TEST-003: Post identifier (1.0.0.post1)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostIdentifier:
    """AC-TEST-003: post identifier (N.N.N.postN) resolves correctly.

    PEP 440 post-releases are ordered after the corresponding base release.
    Unlike pre-releases and dev releases, post-releases are included in
    non-post specifiers (e.g. >=1.0.0 matches 1.0.0.post1) because they
    are strictly newer than the base release.
    """

    @pytest.mark.parametrize(
        "revision,available_tags,expected_tag",
        [
            (
                f"{_TAG_PREFIX}/==1.0.0.post1",
                _POST_TAGS,
                f"{_TAG_PREFIX}/1.0.0.post1",
            ),
            (
                f"{_TAG_PREFIX}/>=1.0.0",
                _POST_TAGS,
                f"{_TAG_PREFIX}/1.0.0.post2",
            ),
            (
                f"{_TAG_PREFIX}/>=1.0.0.post1",
                _POST_TAGS,
                f"{_TAG_PREFIX}/1.0.0.post2",
            ),
        ],
        ids=[
            "exact-post1",
            "gte-base-picks-highest-post",
            "gte-post1-picks-post2",
        ],
    )
    def test_post_constraint_resolves_correctly(self, revision, available_tags, expected_tag):
        """Post-release specifier resolves to the expected tag.

        Given: A constraint that references a post-release version identifier.
        When: resolve_version_constraint() is called with candidate tags.
        Then: Returns the expected tag that satisfies the constraint.
        AC: AC-TEST-003, AC-FUNC-001.
        """
        result = version_constraints.resolve_version_constraint(revision, available_tags)
        assert result == expected_tag, (
            f"Post constraint '{revision}' should resolve to '{expected_tag}', got '{result}'"
        )

    def test_post_revision_is_detected_as_version_constraint(self):
        """A post-release revision string is recognised as a PEP 440 version constraint.

        Given: A revision containing == followed by a post-release version.
        When: is_version_constraint() is called.
        Then: Returns True.
        AC: AC-TEST-003, AC-FUNC-001.
        """
        revision = f"{_TAG_PREFIX}/==1.0.0.post1"
        assert version_constraints.is_version_constraint(revision) is True, (
            f"Post-release revision '{revision}' must be detected as a version constraint"
        )

    def test_post_version_is_newer_than_base(self):
        """Post-release tag is selected over its base release by a >= constraint.

        Given: Tags include 1.0.0 and 1.0.0.post1.
        When: resolve_version_constraint() with >=1.0.0 is called.
        Then: 1.0.0.post1 is selected (it is newer than 1.0.0).
        AC: AC-TEST-003, AC-FUNC-001.
        """
        tags = [f"{_TAG_PREFIX}/1.0.0", f"{_TAG_PREFIX}/1.0.0.post1"]
        result = version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/>=1.0.0", tags)
        assert result == f"{_TAG_PREFIX}/1.0.0.post1", (
            f"Post-release must be ranked higher than the base release, got '{result}'"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Empty constraint raises a clear error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmptyConstraintError:
    """AC-TEST-004: An empty constraint string raises ManifestInvalidRevisionError.

    Passing an empty string as the revision to resolve_version_constraint()
    has no meaningful PEP 440 interpretation (an empty SpecifierSet matches
    any version, which is ambiguous and misleading). The function must detect
    an empty constraint and raise ManifestInvalidRevisionError with a clear
    error message before attempting resolution.
    AC: AC-TEST-004.
    """

    @pytest.mark.parametrize(
        "empty_revision",
        [
            "",
            "   ",
        ],
        ids=[
            "empty-string",
            "whitespace-only",
        ],
    )
    def test_empty_revision_raises_manifest_invalid_revision_error(self, empty_revision):
        """An empty (or whitespace-only) revision raises ManifestInvalidRevisionError.

        Given: A revision string that is empty or contains only whitespace.
        When: resolve_version_constraint() is called.
        Then: Raises ManifestInvalidRevisionError with a non-empty message.
        AC: AC-TEST-004.
        """
        with pytest.raises(error.ManifestInvalidRevisionError) as exc_info:
            version_constraints.resolve_version_constraint(empty_revision, ["refs/tags/1.0.0"])
        assert str(exc_info.value), (
            f"ManifestInvalidRevisionError for empty revision {empty_revision!r} must have a non-empty message"
        )

    def test_empty_constraint_error_message_is_actionable(self):
        """The error message for an empty constraint describes what is invalid.

        Given: An empty string revision.
        When: resolve_version_constraint() raises ManifestInvalidRevisionError.
        Then: The error message contains enough context to identify the problem.
        AC: AC-TEST-004.
        """
        with pytest.raises(error.ManifestInvalidRevisionError) as exc_info:
            version_constraints.resolve_version_constraint("", ["refs/tags/1.0.0"])
        error_text = str(exc_info.value)
        assert error_text, "Error message must not be empty"
        # The message must mention the empty/invalid constraint -- not just say 'no tags found'
        assert (
            "empty" in error_text.lower() or "constraint" in error_text.lower() or "revision" in error_text.lower()
        ), f"Error message should describe the empty/invalid constraint, got: {error_text!r}"
