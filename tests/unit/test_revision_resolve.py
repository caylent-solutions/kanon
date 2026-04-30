"""Tests for ``latest`` / ``==X`` / ``!=X`` / bare-version revision resolution.

Verifies that ``kanon_cli.version`` resolves the four revision-spec forms
covered by RX-03 / RX-05 / RX-14 / RX-23 / RX-24 / RX-26:

- ``latest`` (and the prefixed form ``refs/tags/latest``) resolves to the
  highest semver tag in the available list.
- ``==X.Y.Z`` (and prefixed) resolves to the exact tag ``X.Y.Z``.
- ``!=X.Y.Z`` (and prefixed) resolves to the highest semver tag that is not
  ``X.Y.Z``.
- A bare ``X.Y.Z`` (no operator, no ``refs/tags/`` prefix) is not a PEP 440
  constraint and passes through unchanged so the caller can hand it to
  ``git fetch`` as a tag/branch name. This test pins the contract.

These tests exercise ``_resolve_constraint_from_tags`` directly with a
fixed list of tags rather than going through ``git ls-remote``, keeping
them as pure unit tests with no network or subprocess dependencies.
Implements AC-FUNC-001..004 and AC-TEST-001 of E2-F3-S1-T8.
"""

from __future__ import annotations

import pytest

from kanon_cli.version import (
    _resolve_constraint_from_tags,
    is_version_constraint,
)


_TAGS = [
    "refs/tags/0.9.0",
    "refs/tags/1.0.0",
    "refs/tags/1.1.0",
    "refs/tags/2.0.0",
    "refs/tags/3.0.0",
]


# ---------------------------------------------------------------------------
# is_version_constraint: detection of every form T8 cares about.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsVersionConstraint:
    @pytest.mark.parametrize(
        "rev_spec",
        [
            "latest",
            "refs/tags/latest",
            "==1.0.1",
            "refs/tags/==1.0.1",
            "!=2.0.0",
            "refs/tags/!=2.0.0",
            "<=1.1.0",
            "refs/tags/>=1.0.0,<2.0.0",
            "*",
        ],
    )
    def test_recognised_as_constraint(self, rev_spec: str) -> None:
        assert is_version_constraint(rev_spec) is True

    @pytest.mark.parametrize(
        "rev_spec",
        [
            # Bare X.Y.Z is NOT a constraint -- it's a literal tag/branch.
            "1.0.0",
            "2.0.0",
            "refs/tags/1.0.0",
            "main",
            "refs/heads/main",
            "abcdef0",  # short SHA
        ],
    )
    def test_not_recognised_as_constraint(self, rev_spec: str) -> None:
        assert is_version_constraint(rev_spec) is False


# ---------------------------------------------------------------------------
# RX-14: refs/tags/latest -> highest semver tag.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLatestResolution:
    def test_prefixed_latest_resolves_to_highest_semver(self) -> None:
        assert _resolve_constraint_from_tags("refs/tags/latest", _TAGS) == "refs/tags/3.0.0"

    def test_bare_latest_resolves_to_highest_semver(self) -> None:
        assert _resolve_constraint_from_tags("latest", _TAGS) == "refs/tags/3.0.0"

    def test_latest_skips_non_semver_tags(self) -> None:
        tags = _TAGS + ["refs/tags/random-name", "refs/tags/feature-x"]
        assert _resolve_constraint_from_tags("refs/tags/latest", tags) == "refs/tags/3.0.0"


# ---------------------------------------------------------------------------
# RX-23: refs/tags/==X.Y.Z -> exact tag X.Y.Z.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEqualityResolution:
    def test_prefixed_equality_returns_exact_tag(self) -> None:
        assert _resolve_constraint_from_tags("refs/tags/==1.0.0", _TAGS) == "refs/tags/1.0.0"

    def test_prefixed_equality_returns_exact_minor_release(self) -> None:
        assert _resolve_constraint_from_tags("refs/tags/==1.1.0", _TAGS) == "refs/tags/1.1.0"

    def test_bare_equality_resolves(self) -> None:
        assert _resolve_constraint_from_tags("==2.0.0", _TAGS) == "refs/tags/2.0.0"

    def test_equality_with_no_match_raises(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            _resolve_constraint_from_tags("refs/tags/==9.9.9", _TAGS)
        assert "no tag matching" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# RX-24: refs/tags/!=X.Y.Z -> highest semver tag that is not X.Y.Z.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInequalityResolution:
    def test_prefixed_inequality_excludes_named_tag(self) -> None:
        # Excluding 3.0.0 from {0.9.0, 1.0.0, 1.1.0, 2.0.0, 3.0.0} must
        # resolve to 2.0.0 (highest of the remaining).
        assert _resolve_constraint_from_tags("refs/tags/!=3.0.0", _TAGS) == "refs/tags/2.0.0"

    def test_inequality_excludes_lower_tag(self) -> None:
        # Excluding 1.0.0 must still pick 3.0.0 (the highest remaining).
        assert _resolve_constraint_from_tags("refs/tags/!=1.0.0", _TAGS) == "refs/tags/3.0.0"

    def test_bare_inequality_resolves(self) -> None:
        assert _resolve_constraint_from_tags("!=3.0.0", _TAGS) == "refs/tags/2.0.0"


# ---------------------------------------------------------------------------
# RX-03 / bare-version contract: a bare ``X.Y.Z`` (no operator, no prefix)
# is NOT a PEP 440 constraint. The repo sync path treats it as a literal
# branch/tag name and passes it to git fetch verbatim. Pin that contract.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBareVersionPassthrough:
    @pytest.mark.parametrize("rev", ["1.0.0", "2.0.0", "main"])
    def test_bare_version_is_not_a_constraint(self, rev: str) -> None:
        assert is_version_constraint(rev) is False, f"Bare {rev!r} must not be classified as a PEP 440 constraint"


# ---------------------------------------------------------------------------
# RX-05: compatible release ~=X.Y.Z (existing behaviour, regression guard).
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompatibleReleaseResolution:
    def test_compatible_release_minor_level_picks_highest_within_major(self) -> None:
        # PEP 440 ``~=1.0`` is compatible-release at the minor level, equivalent
        # to ``>=1.0, <2.0``. Within {0.9.0, 1.0.0, 1.1.0, 2.0.0, 3.0.0}
        # the highest match is 1.1.0.
        assert _resolve_constraint_from_tags("refs/tags/~=1.0", _TAGS) == "refs/tags/1.1.0"

    def test_compatible_release_patch_level_picks_highest_within_minor(self) -> None:
        # ``~=1.0.0`` is compatible-release at the patch level, equivalent to
        # ``>=1.0.0, <1.1.0``. Within the test tag list, only 1.0.0 matches.
        assert _resolve_constraint_from_tags("refs/tags/~=1.0.0", _TAGS) == "refs/tags/1.0.0"


# ---------------------------------------------------------------------------
# RX-26: invalid ``==*`` and similar malformed constraints raise.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInvalidConstraintRejected:
    def test_double_equals_wildcard_rejected(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            _resolve_constraint_from_tags("refs/tags/==*", _TAGS)
        assert "invalid version constraint" in str(exc_info.value).lower()

    def test_single_equals_rejected(self) -> None:
        # is_version_constraint detects "=*" as a malformed equality;
        # _resolve_constraint_from_tags then surfaces the error.
        assert is_version_constraint("=*") is True
        with pytest.raises(ValueError):
            _resolve_constraint_from_tags("=*", _TAGS)
