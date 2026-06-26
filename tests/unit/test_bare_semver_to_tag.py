"""Tests for bare PEP 440 version REVISION normalised to refs/tags/<spec>.

A `.kanon` file with `KANON_SOURCE_<name>_REVISION=1.0.0` (or
`<project revision="1.0.0">`) previously failed because kanon passed
the bare value to `repo init -b 1.0.0`, which git resolves as
`refs/heads/1.0.0` (a branch lookup) and fails.

`_normalize_bare_semver_to_tag` prepends `refs/tags/` when the value
is any bare PEP 440 version (no operator, no path prefix), per spec
Section 4.0 rule 3. This includes v-prefixed versions (``v1.0.0``),
single-digit versions (``1``), prereleases, epochs, post/dev releases,
and calendar versions. Everything that fails PEP 440 parsing or
contains ``/`` passes through unchanged.

Implements II-002 / E2-F3-S2-T1; widened per E1-F1-S1-T1.
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
            ("v1.0.0", "refs/tags/v1.0.0"),
            ("1", "refs/tags/1"),
        ],
    )
    def test_bare_pep440_gets_refs_tags_prefix(self, rev_spec: str, expected: str) -> None:
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
        ],
    )
    def test_non_pep440_forms_pass_through(self, rev_spec: str) -> None:
        assert _normalize_bare_semver_to_tag(rev_spec) == rev_spec

    def test_pep440_constraint_passes_through(self) -> None:
        for c in ("~=1.0.0", ">=1.0", "==2.0.0", "!=2.0.0", "*", "latest"):
            assert _normalize_bare_semver_to_tag(c) == c


@pytest.mark.unit
class TestResolveVersionDelegatesToBareNormalizer:
    """`resolve_version()` must apply the bare PEP 440 normalisation to any
    rev_spec that is NOT recognised as a PEP 440 constraint."""

    def test_bare_semver_normalised_via_resolve_version(self) -> None:
        assert resolve_version("file:///fake", "1.0.0") == "refs/tags/1.0.0"
        assert resolve_version("file:///fake", "2.5") == "refs/tags/2.5"

    def test_v_prefixed_normalised_via_resolve_version(self) -> None:
        assert resolve_version("file:///fake", "v1.0.0") == "refs/tags/v1.0.0"

    def test_branch_name_passes_through_resolve_version(self) -> None:
        assert resolve_version("file:///fake", "main") == "main"
        assert resolve_version("file:///fake", "develop") == "develop"

    def test_already_prefixed_tag_passes_through(self) -> None:
        assert resolve_version("file:///fake", "refs/tags/1.0.0") == "refs/tags/1.0.0"
