"""Tests for E2-F3-S2-T1: bare semver REVISION normalised to refs/tags/X.Y.Z.

A `.kanon` file with `KANON_SOURCE_<name>_REVISION=1.0.0` (or
`<project revision="1.0.0">`) previously failed because kanon passed
the bare value to `repo init -b 1.0.0`, which git resolves as
`refs/heads/1.0.0` (a branch lookup) and fails.

`_normalize_bare_semver_to_tag` prepends `refs/tags/` when the value
is a bare digits-and-dots semver (no operator, no path prefix).
Everything else passes through unchanged.

Implements II-002 / E2-F3-S2-T1.
"""

from __future__ import annotations

import pytest

from kanon_cli.version import _normalize_bare_semver_to_tag, resolve_version


@pytest.mark.unit
class TestNormalizeBareSemverToTag:
    @pytest.mark.parametrize(
        "rev_spec,expected",
        [
            ("1.0.0", "refs/tags/1.0.0"),
            ("1.0", "refs/tags/1.0"),
            ("2.0.0", "refs/tags/2.0.0"),
            ("10.20.30", "refs/tags/10.20.30"),
        ],
    )
    def test_bare_semver_gets_refs_tags_prefix(self, rev_spec: str, expected: str) -> None:
        assert _normalize_bare_semver_to_tag(rev_spec) == expected

    @pytest.mark.parametrize(
        "rev_spec",
        [
            "main",
            "develop",
            "feature/x",
            "refs/tags/1.0.0",
            "refs/heads/1.0",
            "abcdef0",
            "abcdef0123456789",
            "v1.0.0",  # leading 'v' -- not bare digits
        ],
    )
    def test_other_forms_pass_through(self, rev_spec: str) -> None:
        assert _normalize_bare_semver_to_tag(rev_spec) == rev_spec

    def test_single_digit_passes_through(self) -> None:
        # `1` alone is not a typical semver tag and could be many things
        # (a branch name, a single-digit version like in old NPM); leave
        # it alone.
        assert _normalize_bare_semver_to_tag("1") == "1"

    def test_pep440_constraint_passes_through(self) -> None:
        # Constraints are handled separately by `is_version_constraint` /
        # `_resolve_constraint_from_tags`; the normaliser must NOT touch
        # them (their resolution path returns a refs/tags/... value).
        for c in ("~=1.0.0", ">=1.0", "==2.0.0", "!=2.0.0", "*", "latest"):
            assert _normalize_bare_semver_to_tag(c) == c


@pytest.mark.unit
class TestResolveVersionDelegatesToBareNormalizer:
    """`resolve_version()` must apply the bare-semver normalisation to any
    rev_spec that is NOT recognised as a PEP 440 constraint."""

    def test_bare_semver_normalised_via_resolve_version(self) -> None:
        # No git ls-remote needed -- normalisation happens in the early
        # passthrough branch.
        assert resolve_version("file:///fake", "1.0.0") == "refs/tags/1.0.0"
        assert resolve_version("file:///fake", "2.5") == "refs/tags/2.5"

    def test_branch_name_passes_through_resolve_version(self) -> None:
        assert resolve_version("file:///fake", "main") == "main"
        assert resolve_version("file:///fake", "develop") == "develop"

    def test_already_prefixed_tag_passes_through(self) -> None:
        assert resolve_version("file:///fake", "refs/tags/1.0.0") == "refs/tags/1.0.0"
