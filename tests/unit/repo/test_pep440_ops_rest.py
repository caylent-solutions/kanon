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

"""Unit tests for PEP 440 less-or-equal (<=), less-than (<), equality (==),
inequality (!=), and wildcard (*) operators in version_constraints.

Covers:
- AC-TEST-001: <=2.0.0 and <2.0.0 resolve less-or-equal / less-than.
- AC-TEST-002: ==1.2.0 resolves equality.
- AC-TEST-003: !=1.1.0 resolves inequality.
- AC-TEST-004: * resolves to latest-matching-version.
- AC-FUNC-001: All remaining PEP 440 operators match spec.

Spec references:
- AC-TEST-001: Less-or-equal (<=) and less-than (<) operators per PEP 440.
- AC-TEST-002: Equality (==) operator per PEP 440.
- AC-TEST-003: Inequality (!=) operator per PEP 440.
- AC-TEST-004: Wildcard (*) resolution per spec.
- AC-FUNC-001: All remaining operators conform to PEP 440 specification.
"""

import pytest

from kanon_cli.repo import error, version_constraints

# Common tag prefix used across all tests.
_TAG_PREFIX = "refs/tags/dev/python/quality-agent"

# Available tags shared by most test cases.
_AVAILABLE_TAGS = [
    f"{_TAG_PREFIX}/1.0.0",
    f"{_TAG_PREFIX}/1.1.0",
    f"{_TAG_PREFIX}/1.2.0",
    f"{_TAG_PREFIX}/1.2.3",
    f"{_TAG_PREFIX}/2.0.0",
    f"{_TAG_PREFIX}/2.1.0",
    f"{_TAG_PREFIX}/3.0.0",
]


@pytest.mark.unit
class TestLessOrEqualOperator:
    """AC-TEST-001 (<=): resolves to highest version satisfying the upper bound (inclusive).

    The less-or-equal operator (<=) matches all versions that are
    less than or equal to the specified version and returns the highest one.
    The bound is inclusive, so the specified version itself is eligible.
    """

    @pytest.mark.parametrize(
        "constraint,available_tags,expected_tag",
        [
            (
                f"{_TAG_PREFIX}/<=2.0.0",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/2.0.0",
            ),
            (
                f"{_TAG_PREFIX}/<=1.2.0",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/1.2.0",
            ),
            (
                f"{_TAG_PREFIX}/<=1.2.3",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/1.2.3",
            ),
        ],
        ids=[
            "le-upper-bound-2.0.0-picks-exact",
            "le-upper-bound-1.2.0-picks-exact",
            "le-upper-bound-1.2.3-picks-exact",
        ],
    )
    def test_less_or_equal_picks_highest_below_bound(self, constraint, available_tags, expected_tag):
        """<=X.Y.Z resolves to the highest version that is <= the specified bound.

        Given: A constraint using <= and a set of available tags.
        When: resolve_version_constraint() is called.
        Then: Returns the highest tag satisfying the upper-bound constraint.
        AC: AC-TEST-001.
        """
        result = version_constraints.resolve_version_constraint(constraint, available_tags)
        assert result == expected_tag, (
            f"<= constraint '{constraint}' should resolve to '{expected_tag}', got '{result}'"
        )

    def test_less_or_equal_includes_exact_bound_version(self):
        """<=2.0.0 must include 2.0.0 itself (upper bound is inclusive).

        Given: 2.0.0 is available and constraint is <=2.0.0.
        When: resolve_version_constraint() is called.
        Then: Returns 2.0.0 (bound is inclusive).
        AC: AC-TEST-001 / AC-FUNC-001.
        """
        tags = [
            f"{_TAG_PREFIX}/1.0.0",
            f"{_TAG_PREFIX}/2.0.0",
        ]
        result = version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/<=2.0.0", tags)
        assert result == f"{_TAG_PREFIX}/2.0.0"

    def test_less_or_equal_excludes_versions_above_bound(self):
        """<=2.0.0 must not match 2.1.0 or 3.0.0 (above bound).

        Given: Tags include 2.0.0 (at bound), 2.1.0 and 3.0.0 (above bound).
        When: resolve_version_constraint() is called with <=2.0.0.
        Then: Returns 2.0.0 and does not return 2.1.0 or 3.0.0.
        AC: AC-TEST-001 / AC-FUNC-001.
        """
        result = version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/<=2.0.0", _AVAILABLE_TAGS)
        assert result == f"{_TAG_PREFIX}/2.0.0"
        assert result != f"{_TAG_PREFIX}/2.1.0"
        assert result != f"{_TAG_PREFIX}/3.0.0"

    def test_less_or_equal_is_detected_as_constraint(self):
        """<= revision strings are recognized as version constraints.

        Given: A revision string using the <= operator.
        When: is_version_constraint() is called.
        Then: Returns True.
        AC: AC-FUNC-001.
        """
        assert version_constraints.is_version_constraint(f"{_TAG_PREFIX}/<=2.0.0") is True
        assert version_constraints.is_version_constraint("<=1.0") is True

    def test_less_or_equal_no_match_raises_error(self):
        """<=0.1.0 with no matching tags raises ManifestInvalidRevisionError.

        Given: All available tags are above the upper bound.
        When: resolve_version_constraint() is called with <=0.1.0.
        Then: ManifestInvalidRevisionError is raised.
        AC: AC-TEST-001 / AC-FUNC-001.
        """
        with pytest.raises(error.ManifestInvalidRevisionError):
            version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/<=0.1.0", _AVAILABLE_TAGS)


@pytest.mark.unit
class TestLessThanOperator:
    """AC-TEST-001 (<): resolves to highest version strictly below the bound (exclusive).

    The less-than operator (<) matches all versions strictly less than the
    specified version and returns the highest one. The bound itself is excluded.
    """

    @pytest.mark.parametrize(
        "constraint,available_tags,expected_tag",
        [
            (
                f"{_TAG_PREFIX}/<2.0.0",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/1.2.3",
            ),
            (
                f"{_TAG_PREFIX}/<1.2.0",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/1.1.0",
            ),
            (
                f"{_TAG_PREFIX}/<3.0.0",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/2.1.0",
            ),
        ],
        ids=[
            "lt-below-2.0.0-picks-highest-below",
            "lt-below-1.2.0-picks-highest-below",
            "lt-below-3.0.0-picks-highest-below",
        ],
    )
    def test_less_than_picks_highest_strictly_below_bound(self, constraint, available_tags, expected_tag):
        """<X.Y.Z resolves to the highest version strictly less than the bound.

        Given: A constraint using < and a set of available tags.
        When: resolve_version_constraint() is called.
        Then: Returns the highest tag strictly below the bound.
        AC: AC-TEST-001.
        """
        result = version_constraints.resolve_version_constraint(constraint, available_tags)
        assert result == expected_tag, f"< constraint '{constraint}' should resolve to '{expected_tag}', got '{result}'"

    def test_less_than_excludes_exact_bound_version(self):
        """<2.0.0 must not match 2.0.0 itself (upper bound is exclusive).

        Given: Tags include 1.2.3 (below) and 2.0.0 (at the bound).
        When: resolve_version_constraint() is called with <2.0.0.
        Then: Returns 1.2.3 and does not return 2.0.0.
        AC: AC-TEST-001 / AC-FUNC-001.
        """
        result = version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/<2.0.0", _AVAILABLE_TAGS)
        assert result == f"{_TAG_PREFIX}/1.2.3"
        assert result != f"{_TAG_PREFIX}/2.0.0"

    def test_less_than_is_detected_as_constraint(self):
        """< revision strings are recognized as version constraints.

        Given: A revision string using the < operator.
        When: is_version_constraint() is called.
        Then: Returns True.
        AC: AC-FUNC-001.
        """
        assert version_constraints.is_version_constraint(f"{_TAG_PREFIX}/<2.0.0") is True
        assert version_constraints.is_version_constraint("<1.0") is True

    def test_less_than_no_match_raises_error(self):
        """<1.0.0 with no tags below the bound raises ManifestInvalidRevisionError.

        Given: All available tags are at or above the bound.
        When: resolve_version_constraint() is called with <1.0.0.
        Then: ManifestInvalidRevisionError is raised.
        AC: AC-TEST-001 / AC-FUNC-001.
        """
        tags = [f"{_TAG_PREFIX}/1.0.0"]
        with pytest.raises(error.ManifestInvalidRevisionError):
            version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/<1.0.0", tags)


@pytest.mark.unit
class TestEqualityOperator:
    """AC-TEST-002 (==): resolves to the exact version specified.

    The equality operator (==) matches exactly one version and returns it.
    """

    @pytest.mark.parametrize(
        "constraint,available_tags,expected_tag",
        [
            (
                f"{_TAG_PREFIX}/==1.2.0",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/1.2.0",
            ),
            (
                f"{_TAG_PREFIX}/==2.0.0",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/2.0.0",
            ),
            (
                f"{_TAG_PREFIX}/==1.0.0",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/1.0.0",
            ),
        ],
        ids=[
            "eq-exact-1.2.0",
            "eq-exact-2.0.0",
            "eq-exact-1.0.0",
        ],
    )
    def test_equality_resolves_exact_version(self, constraint, available_tags, expected_tag):
        """==X.Y.Z resolves to exactly the version specified.

        Given: A constraint using == and a set of available tags.
        When: resolve_version_constraint() is called.
        Then: Returns the tag matching the exact version.
        AC: AC-TEST-002.
        """
        result = version_constraints.resolve_version_constraint(constraint, available_tags)
        assert result == expected_tag, (
            f"== constraint '{constraint}' should resolve to '{expected_tag}', got '{result}'"
        )

    def test_equality_does_not_match_adjacent_versions(self):
        """==1.2.0 must not match 1.2.3 or any other version.

        Given: Tags include 1.2.0, 1.2.3, and 2.0.0.
        When: resolve_version_constraint() is called with ==1.2.0.
        Then: Returns 1.2.0 only.
        AC: AC-TEST-002 / AC-FUNC-001.
        """
        result = version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/==1.2.0", _AVAILABLE_TAGS)
        assert result == f"{_TAG_PREFIX}/1.2.0"
        assert result != f"{_TAG_PREFIX}/1.2.3"
        assert result != f"{_TAG_PREFIX}/2.0.0"

    def test_equality_is_detected_as_constraint(self):
        """== revision strings are recognized as version constraints.

        Given: A revision string using the == operator.
        When: is_version_constraint() is called.
        Then: Returns True.
        AC: AC-FUNC-001.
        """
        assert version_constraints.is_version_constraint(f"{_TAG_PREFIX}/==1.2.0") is True
        assert version_constraints.is_version_constraint("==2.3.4") is True

    def test_equality_no_match_raises_error(self):
        """==9.9.9 with no matching tags raises ManifestInvalidRevisionError.

        Given: 9.9.9 does not appear in available_tags.
        When: resolve_version_constraint() is called with ==9.9.9.
        Then: ManifestInvalidRevisionError is raised.
        AC: AC-TEST-002 / AC-FUNC-001.
        """
        with pytest.raises(error.ManifestInvalidRevisionError):
            version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/==9.9.9", _AVAILABLE_TAGS)


@pytest.mark.unit
class TestInequalityOperator:
    """AC-TEST-003 (!=): resolves to the highest version that is not excluded.

    The inequality operator (!=) matches all versions except the specified
    one and returns the highest matching version.
    """

    @pytest.mark.parametrize(
        "constraint,available_tags,expected_tag",
        [
            (
                f"{_TAG_PREFIX}/!=1.1.0",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/3.0.0",
            ),
            (
                f"{_TAG_PREFIX}/!=3.0.0",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/2.1.0",
            ),
            (
                f"{_TAG_PREFIX}/!=2.1.0",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/3.0.0",
            ),
        ],
        ids=[
            "ne-excludes-1.1.0-picks-highest",
            "ne-excludes-3.0.0-picks-second-highest",
            "ne-excludes-2.1.0-picks-highest",
        ],
    )
    def test_inequality_picks_highest_non_excluded_version(self, constraint, available_tags, expected_tag):
        """!=X.Y.Z resolves to the highest version that is not the excluded version.

        Given: A constraint using != and a set of available tags.
        When: resolve_version_constraint() is called.
        Then: Returns the highest tag that is not the excluded version.
        AC: AC-TEST-003.
        """
        result = version_constraints.resolve_version_constraint(constraint, available_tags)
        assert result == expected_tag, (
            f"!= constraint '{constraint}' should resolve to '{expected_tag}', got '{result}'"
        )

    def test_inequality_excludes_specified_version(self):
        """!=1.1.0 must not return 1.1.0.

        Given: Tags include 1.1.0 (excluded) and 3.0.0 (highest other).
        When: resolve_version_constraint() is called with !=1.1.0.
        Then: Does not return 1.1.0; returns 3.0.0 instead.
        AC: AC-TEST-003 / AC-FUNC-001.
        """
        result = version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/!=1.1.0", _AVAILABLE_TAGS)
        assert result != f"{_TAG_PREFIX}/1.1.0"
        assert result == f"{_TAG_PREFIX}/3.0.0"

    def test_inequality_is_detected_as_constraint(self):
        """!= revision strings are recognized as version constraints.

        Given: A revision string using the != operator.
        When: is_version_constraint() is called.
        Then: Returns True.
        AC: AC-FUNC-001.
        """
        assert version_constraints.is_version_constraint(f"{_TAG_PREFIX}/!=1.0.0") is True
        assert version_constraints.is_version_constraint("!=2.3.4") is True

    def test_inequality_single_tag_excluded_raises_error(self):
        """!=1.0.0 when 1.0.0 is the only tag raises ManifestInvalidRevisionError.

        Given: Only 1.0.0 is available and it is excluded by !=.
        When: resolve_version_constraint() is called with !=1.0.0.
        Then: ManifestInvalidRevisionError is raised (no remaining candidates).
        AC: AC-TEST-003 / AC-FUNC-001.
        """
        tags = [f"{_TAG_PREFIX}/1.0.0"]
        with pytest.raises(error.ManifestInvalidRevisionError):
            version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/!=1.0.0", tags)


@pytest.mark.unit
class TestWildcardOperator:
    """AC-TEST-004 (*): resolves to the highest available version.

    The wildcard operator (*) selects the highest version from all
    available tags under the given prefix.
    """

    @pytest.mark.parametrize(
        "constraint,available_tags,expected_tag",
        [
            (
                f"{_TAG_PREFIX}/*",
                _AVAILABLE_TAGS,
                f"{_TAG_PREFIX}/3.0.0",
            ),
            (
                f"{_TAG_PREFIX}/*",
                [
                    f"{_TAG_PREFIX}/1.0.0",
                    f"{_TAG_PREFIX}/2.0.0",
                ],
                f"{_TAG_PREFIX}/2.0.0",
            ),
            (
                f"{_TAG_PREFIX}/*",
                [f"{_TAG_PREFIX}/1.2.3"],
                f"{_TAG_PREFIX}/1.2.3",
            ),
        ],
        ids=[
            "wildcard-picks-3.0.0-from-full-set",
            "wildcard-picks-highest-from-two",
            "wildcard-single-tag-returns-only-tag",
        ],
    )
    def test_wildcard_picks_highest_available_version(self, constraint, available_tags, expected_tag):
        """* resolves to the highest version from all available tags.

        Given: A wildcard constraint and a set of available tags.
        When: resolve_version_constraint() is called.
        Then: Returns the tag for the highest version.
        AC: AC-TEST-004.
        """
        result = version_constraints.resolve_version_constraint(constraint, available_tags)
        assert result == expected_tag, (
            f"Wildcard constraint '{constraint}' should resolve to '{expected_tag}', got '{result}'"
        )

    def test_wildcard_is_detected_as_constraint(self):
        """* revision strings are recognized as version constraints.

        Given: A revision string with a wildcard * in the last path component.
        When: is_version_constraint() is called.
        Then: Returns True.
        AC: AC-TEST-004 / AC-FUNC-001.
        """
        assert version_constraints.is_version_constraint(f"{_TAG_PREFIX}/*") is True
        assert version_constraints.is_version_constraint("*") is True

    def test_wildcard_returns_version_greater_than_all_others(self):
        """* must return a version that is >= all other returned candidates.

        Given: An unsorted set of tags.
        When: resolve_version_constraint() is called with *.
        Then: The returned version is the maximum among all candidates.
        AC: AC-TEST-004 / AC-FUNC-001.
        """
        tags = [
            f"{_TAG_PREFIX}/1.2.7",
            f"{_TAG_PREFIX}/1.2.0",
            f"{_TAG_PREFIX}/2.0.0",
            f"{_TAG_PREFIX}/1.3.0",
        ]
        result = version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/*", tags)
        assert result == f"{_TAG_PREFIX}/2.0.0"

    def test_wildcard_no_parseable_tags_raises_error(self):
        """* with no parseable version tags raises ManifestInvalidRevisionError.

        Given: Available tags have no parseable PEP 440 version components.
        When: resolve_version_constraint() is called with *.
        Then: ManifestInvalidRevisionError is raised.
        AC: AC-TEST-004 / AC-FUNC-001.
        """
        tags = [
            f"{_TAG_PREFIX}/not-a-version",
            f"{_TAG_PREFIX}/also_bad",
        ]
        with pytest.raises(error.ManifestInvalidRevisionError):
            version_constraints.resolve_version_constraint(f"{_TAG_PREFIX}/*", tags)
