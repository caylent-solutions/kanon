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

"""Unit tests for PEP 440 tilde-equal (~=) and greater-or-equal (>=) operators.

Covers AC-TEST-001: ~=1.2.0 resolves compatible-release range correctly.
Covers AC-TEST-002: >=1.0.0 resolves greater-or-equal correctly.

Spec references:
- AC-TEST-001: Compatible-release (~=) operator resolution per PEP 440 section 8.3.
- AC-TEST-002: Greater-or-equal (>=) operator resolution per PEP 440 section 8.3.
- AC-FUNC-001: Compatible-release and greater-or-equal operators match PEP 440.
"""

import pytest

from kanon_cli.repo import version_constraints


@pytest.mark.unit
class TestCompatibleReleaseOperator:
    """AC-TEST-001: ~= operator resolves compatible-release range per PEP 440.

    The compatible-release operator (~=) matches any version that is
    greater than or equal to the specified version while remaining
    compatible at the next-to-last digit level. For example:
    - ~=1.2.0 matches 1.2.0, 1.2.1, 1.2.7 but not 1.3.0 or 2.0.0.
    - ~=1.2   matches 1.2.0, 1.2.7, 1.3.0 but not 2.0.0.
    """

    @pytest.mark.parametrize(
        "constraint,available_tags,expected_tag",
        [
            (
                "refs/tags/project/~=1.2.0",
                [
                    "refs/tags/project/1.0.0",
                    "refs/tags/project/1.2.0",
                    "refs/tags/project/1.2.3",
                    "refs/tags/project/1.2.7",
                    "refs/tags/project/1.3.0",
                    "refs/tags/project/2.0.0",
                ],
                "refs/tags/project/1.2.7",
            ),
            (
                "refs/tags/project/~=1.2.0",
                [
                    "refs/tags/project/1.2.0",
                    "refs/tags/project/1.2.1",
                ],
                "refs/tags/project/1.2.1",
            ),
            (
                "refs/tags/project/~=2.0.0",
                [
                    "refs/tags/project/1.9.9",
                    "refs/tags/project/2.0.0",
                    "refs/tags/project/2.0.5",
                    "refs/tags/project/2.1.0",
                    "refs/tags/project/3.0.0",
                ],
                "refs/tags/project/2.0.5",
            ),
        ],
        ids=["patch-tilde-picks-highest-in-range", "patch-tilde-single-above", "major-tilde-stays-in-minor"],
    )
    def test_compatible_release_picks_highest_matching_version(self, constraint, available_tags, expected_tag):
        """~=X.Y.Z resolves to the highest version in the compatible-release range.

        Given: A constraint using ~= and a set of available tags.
        When: resolve_version_constraint() is called.
        Then: Returns the highest tag satisfying the compatible-release range.
        AC: AC-TEST-001.
        """
        result = version_constraints.resolve_version_constraint(constraint, available_tags)
        assert result == expected_tag, (
            f"~= constraint '{constraint}' should resolve to '{expected_tag}', got '{result}'"
        )

    def test_compatible_release_excludes_next_major_version(self):
        """~=1.2.0 must not match 1.3.0 or 2.0.0 (different minor or major).

        Given: Tags include 1.2.7 (compatible) and 1.3.0, 2.0.0 (incompatible).
        When: resolve_version_constraint() is called with ~=1.2.0.
        Then: Returns 1.2.7 and does not return 1.3.0 or 2.0.0.
        AC: AC-TEST-001 / AC-FUNC-001.
        """
        tags = [
            "refs/tags/lib/1.2.0",
            "refs/tags/lib/1.2.7",
            "refs/tags/lib/1.3.0",
            "refs/tags/lib/2.0.0",
        ]
        result = version_constraints.resolve_version_constraint("refs/tags/lib/~=1.2.0", tags)
        assert result == "refs/tags/lib/1.2.7"
        assert result != "refs/tags/lib/1.3.0"
        assert result != "refs/tags/lib/2.0.0"

    def test_compatible_release_is_detected_as_constraint(self):
        """~= revision strings are recognized as version constraints.

        Given: A revision string using the ~= operator.
        When: is_version_constraint() is called.
        Then: Returns True.
        AC: AC-FUNC-001.
        """
        assert version_constraints.is_version_constraint("refs/tags/project/~=1.2.0") is True
        assert version_constraints.is_version_constraint("~=1.0") is True


@pytest.mark.unit
class TestGreaterOrEqualOperator:
    """AC-TEST-002: >= operator resolves to the highest version satisfying the lower bound.

    The greater-or-equal operator (>=) matches any version that is
    greater than or equal to the specified version, including across
    major versions, unless combined with an upper-bound specifier.
    """

    @pytest.mark.parametrize(
        "constraint,available_tags,expected_tag",
        [
            (
                "refs/tags/project/>=1.0.0",
                [
                    "refs/tags/project/1.0.0",
                    "refs/tags/project/1.2.3",
                    "refs/tags/project/2.0.0",
                    "refs/tags/project/3.0.0",
                ],
                "refs/tags/project/3.0.0",
            ),
            (
                "refs/tags/project/>=2.0.0",
                [
                    "refs/tags/project/1.9.9",
                    "refs/tags/project/2.0.0",
                    "refs/tags/project/2.5.0",
                ],
                "refs/tags/project/2.5.0",
            ),
            (
                "refs/tags/project/>=1.0.0",
                [
                    "refs/tags/project/1.0.0",
                ],
                "refs/tags/project/1.0.0",
            ),
        ],
        ids=["ge-picks-highest-across-majors", "ge-picks-highest-above-floor", "ge-exact-lower-bound"],
    )
    def test_greater_or_equal_picks_highest_matching_version(self, constraint, available_tags, expected_tag):
        """>=X.Y.Z resolves to the highest version that is >= the lower bound.

        Given: A constraint using >= and a set of available tags.
        When: resolve_version_constraint() is called.
        Then: Returns the highest tag satisfying the lower-bound constraint.
        AC: AC-TEST-002.
        """
        result = version_constraints.resolve_version_constraint(constraint, available_tags)
        assert result == expected_tag, (
            f">= constraint '{constraint}' should resolve to '{expected_tag}', got '{result}'"
        )

    def test_greater_or_equal_excludes_versions_below_lower_bound(self):
        """>=2.0.0 must not match 1.9.9 or any version below 2.0.0.

        Given: Tags include 1.9.9 (below bound) and 2.0.0, 2.1.0 (at or above).
        When: resolve_version_constraint() is called with >=2.0.0.
        Then: Returns 2.1.0 and does not return 1.9.9.
        AC: AC-TEST-002 / AC-FUNC-001.
        """
        tags = [
            "refs/tags/lib/1.9.9",
            "refs/tags/lib/2.0.0",
            "refs/tags/lib/2.1.0",
        ]
        result = version_constraints.resolve_version_constraint("refs/tags/lib/>=2.0.0", tags)
        assert result == "refs/tags/lib/2.1.0"
        assert result != "refs/tags/lib/1.9.9"

    def test_greater_or_equal_includes_exact_lower_bound_version(self):
        """>=1.0.0 must include 1.0.0 itself (lower bound is inclusive).

        Given: Only 1.0.0 is available and constraint is >=1.0.0.
        When: resolve_version_constraint() is called.
        Then: Returns 1.0.0 (bound is inclusive).
        AC: AC-TEST-002 / AC-FUNC-001.
        """
        tags = ["refs/tags/lib/0.9.9", "refs/tags/lib/1.0.0"]
        result = version_constraints.resolve_version_constraint("refs/tags/lib/>=1.0.0", tags)
        assert result == "refs/tags/lib/1.0.0"

    def test_greater_or_equal_is_detected_as_constraint(self):
        """>= revision strings are recognized as version constraints.

        Given: A revision string using the >= operator.
        When: is_version_constraint() is called.
        Then: Returns True.
        AC: AC-FUNC-001.
        """
        assert version_constraints.is_version_constraint("refs/tags/project/>=1.0.0") is True
        assert version_constraints.is_version_constraint(">=2.3.4") is True
