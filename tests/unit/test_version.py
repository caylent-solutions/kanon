"""Tests for fuzzy version resolution."""

from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.version import (
    _normalize_bare_semver_to_tag,
    is_version_constraint,
    _list_tags,
    resolve_version,
)


def _mock_ls_remote(tags: list[str]) -> MagicMock:
    """Build a mock subprocess.run result for git ls-remote with full refs."""
    output = "\n".join(f"abc123\t{t}" for t in tags)
    return MagicMock(returncode=0, stdout=output, stderr="")


@pytest.mark.unit
class TestIsVersionConstraint:
    """Verify PEP 440 constraint detection in the last path component."""

    @pytest.mark.parametrize(
        "rev_spec",
        [
            "*",
            "~=1.0.0",
            ">=1.0.0",
            "<=2.0.0",
            ">1.0.0",
            "<2.0.0",
            "==1.2.3",
            "!=1.0.1",
            ">=1.0.0,<2.0.0",
            "refs/tags/*",
            "refs/tags/~=1.0.0",
            "refs/tags/dev/python/my-lib/~=1.0.0",
            "refs/tags/>=1.0.0,<2.0.0",
        ],
    )
    def test_detects_constraints(self, rev_spec: str) -> None:
        assert is_version_constraint(rev_spec) is True

    @pytest.mark.parametrize(
        "rev_spec",
        ["main", "refs/tags/1.1.2", "some-branch", "caylent-2.0.0", "v1.0.0"],
    )
    def test_ignores_plain_refs(self, rev_spec: str) -> None:
        assert is_version_constraint(rev_spec) is False


@pytest.mark.unit
class TestResolveVersionPassthrough:
    """Verify plain branch/tag names pass through unchanged.

    Note: v-prefixed versions (e.g. ``v1.0.0``) are accepted by PEP 440
    and are normalised to ``refs/tags/v1.0.0`` per spec Section 4.0 rule 3.
    Only strings that fail ``packaging.version.Version`` parsing -- or that
    contain a ``/`` -- are passed through unchanged.
    """

    @pytest.mark.parametrize(
        "rev_spec",
        ["main", "caylent-2.0.0", "some-branch", "refs/tags/1.1.2"],
        ids=["main", "caylent-tag", "branch", "full-tag-ref"],
    )
    def test_passthrough(self, rev_spec: str) -> None:
        result = resolve_version("https://example.com/repo.git", rev_spec)
        assert result == rev_spec

    def test_v_prefixed_version_normalises_to_refs_tags(self) -> None:
        """v-prefixed strings are valid PEP 440 and normalise to refs/tags/."""
        result = resolve_version("https://example.com/repo.git", "v1.0.0")
        assert result == "refs/tags/v1.0.0"


@pytest.mark.unit
class TestResolveVersionBareConstraint:
    """Verify bare PEP 440 constraints (no refs/tags/ prefix) resolve to full refs."""

    def test_compatible_release(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/1.0.3", "refs/tags/1.1.0", "refs/tags/2.0.0"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version("https://example.com/repo.git", "~=1.0.0")
            assert result == "refs/tags/1.0.3"

    def test_range_specifier(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/1.5.0", "refs/tags/2.0.0"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version("https://example.com/repo.git", ">=1.0.0,<2.0.0")
            assert result == "refs/tags/1.5.0"

    def test_exact_match(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/1.2.3", "refs/tags/2.0.0"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version("https://example.com/repo.git", "==1.2.3")
            assert result == "refs/tags/1.2.3"

    def test_not_equal(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/1.0.1", "refs/tags/1.0.2"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version("https://example.com/repo.git", "!=1.0.1")
            assert result == "refs/tags/1.0.2"

    def test_greater_than_or_equal(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/2.0.0", "refs/tags/3.0.0"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version("https://example.com/repo.git", ">=2.0.0")
            assert result == "refs/tags/3.0.0"

    def test_less_than(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/2.0.0", "refs/tags/3.0.0"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version("https://example.com/repo.git", "<2.0.0")
            assert result == "refs/tags/1.0.0"

    def test_wildcard_returns_latest(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/2.0.0", "refs/tags/3.0.0"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version("https://example.com/repo.git", "*")
            assert result == "refs/tags/3.0.0"

    def test_no_match_exits(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/2.0.0"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            with pytest.raises(SystemExit):
                resolve_version("https://example.com/repo.git", "==9.9.9")

    def test_no_tags_exits(self) -> None:
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with pytest.raises(SystemExit):
                resolve_version("https://example.com/repo.git", "~=1.0.0")

    def test_git_failure_exits(self) -> None:
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="fatal: not found")
            with pytest.raises(SystemExit):
                resolve_version("https://example.com/repo.git", "~=1.0.0")


@pytest.mark.unit
class TestResolveVersionPrefixedConstraint:
    """Verify prefixed constraints (refs/tags/<prefix>/<constraint>) resolve correctly."""

    def test_refs_tags_prefix_compatible_release(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/1.1.0", "refs/tags/1.1.2", "refs/tags/2.0.0"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version("https://example.com/repo.git", "refs/tags/~=1.1.0")
            assert result == "refs/tags/1.1.2"

    def test_refs_tags_prefix_wildcard(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/1.1.0", "refs/tags/1.1.2"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version("https://example.com/repo.git", "refs/tags/*")
            assert result == "refs/tags/1.1.2"

    def test_refs_tags_prefix_range(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/1.5.0", "refs/tags/2.0.0"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version("https://example.com/repo.git", "refs/tags/>=1.0.0,<2.0.0")
            assert result == "refs/tags/1.5.0"

    def test_namespaced_prefix(self) -> None:
        """Tags with a deeper namespace prefix are filtered correctly."""
        tags = [
            "refs/tags/dev/python/my-lib/1.0.0",
            "refs/tags/dev/python/my-lib/1.2.0",
            "refs/tags/dev/python/my-lib/1.2.7",
            "refs/tags/dev/python/other-lib/1.5.0",
        ]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version(
                "https://example.com/repo.git",
                "refs/tags/dev/python/my-lib/~=1.2.0",
            )
            assert result == "refs/tags/dev/python/my-lib/1.2.7"

    def test_no_tags_under_prefix_exits(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/1.1.0"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            with pytest.raises(SystemExit):
                resolve_version(
                    "https://example.com/repo.git",
                    "refs/tags/dev/python/missing-lib/~=1.0.0",
                )


@pytest.mark.unit
class TestListTags:
    """Verify git ls-remote tag parsing returns full ref paths."""

    def test_parses_tags(self) -> None:
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="abc\trefs/tags/1.0.0\ndef\trefs/tags/2.0.0\nghi\trefs/tags/2.0.0^{}\n",
                stderr="",
            )
            tags = _list_tags("https://example.com/repo.git")
            assert tags == ["refs/tags/1.0.0", "refs/tags/2.0.0"]

    def test_empty_output(self) -> None:
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            tags = _list_tags("https://example.com/repo.git")
            assert tags == []

    def test_git_failure_exits(self) -> None:
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="fatal")
            with pytest.raises(SystemExit):
                _list_tags("https://example.com/repo.git")


@pytest.mark.unit
class TestNormalizeBareWidenedPep440:
    """AC-FUNC-001 through AC-FUNC-007, AC-TEST-001, AC-TEST-002.

    Verify that _normalize_bare_semver_to_tag accepts any PEP 440 Version
    (spec Section 4.0 rule 3) and still passes through non-PEP-440 inputs.
    """

    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            # AC-FUNC-001: prerelease
            ("1.0.0a1", "refs/tags/1.0.0a1"),
            # AC-FUNC-001: release candidate
            ("1.0.0rc2", "refs/tags/1.0.0rc2"),
            # AC-FUNC-001: beta
            ("1.0.0b3", "refs/tags/1.0.0b3"),
            # AC-FUNC-002: local version
            ("1.0.0+local.build", "refs/tags/1.0.0+local.build"),
            # AC-FUNC-003: calendar version
            ("2026.4.1", "refs/tags/2026.4.1"),
            # AC-FUNC-004: epoch
            ("1!2.0.0", "refs/tags/1!2.0.0"),
            # AC-FUNC-005: post-release
            ("1.0.0.post1", "refs/tags/1.0.0.post1"),
            # AC-FUNC-006: dev-release
            ("1.0.0.dev0", "refs/tags/1.0.0.dev0"),
        ],
        ids=[
            "prerelease-alpha",
            "prerelease-rc",
            "prerelease-beta",
            "local-version",
            "calendar-version",
            "epoch",
            "post-release",
            "dev-release",
        ],
    )
    def test_widened_pep440_shapes_normalize_to_tag(self, spec: str, expected: str) -> None:
        assert _normalize_bare_semver_to_tag(spec) == expected

    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            # AC-FUNC-007: narrow shapes still resolve
            ("1", "refs/tags/1"),
            ("1.0", "refs/tags/1.0"),
            ("1.0.0", "refs/tags/1.0.0"),
            # AC-TEST-002: pass-through -- already-prefixed refs
            ("refs/tags/x", "refs/tags/x"),
            ("refs/heads/main", "refs/heads/main"),
            # AC-TEST-002: pass-through -- branch names that fail PEP 440
            ("main", "main"),
            ("develop", "develop"),
            # AC-TEST-002: pass-through -- any input containing '/'
            ("feature/foo", "feature/foo"),
            ("subpackage/1.0.0", "subpackage/1.0.0"),
            # AC-TEST-002: pass-through -- 40-char hex SHA
            ("a" * 40, "a" * 40),
            # AC-TEST-002: pass-through -- 64-char hex SHA
            ("b" * 64, "b" * 64),
        ],
        ids=[
            "single-digit",
            "two-part-semver",
            "three-part-semver",
            "refs-tags-x",
            "refs-heads-main",
            "branch-main",
            "branch-develop",
            "feature-slash",
            "monorepo-prefixed",
            "sha-40",
            "sha-64",
        ],
    )
    def test_passthrough_and_narrow_preserved(self, spec: str, expected: str) -> None:
        assert _normalize_bare_semver_to_tag(spec) == expected
