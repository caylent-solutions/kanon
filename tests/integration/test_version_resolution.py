"""Integration tests for version constraint resolution (20 tests).

Exercises is_version_constraint() and resolve_version() against mocked
git ls-remote output.  Tests cover all constraint operators, wildcard,
prefixed constraints, namespaced tags, and error paths.
"""

from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.version import _list_tags, is_version_constraint, resolve_version


# ---------------------------------------------------------------------------
# AC-FUNC-007: Version resolution integration tests (20 tests)
# ---------------------------------------------------------------------------


def _mock_ls_remote(tags: list[str]) -> MagicMock:
    """Build a mock subprocess.run result for git ls-remote."""
    output = "\n".join(f"abc123\t{t}" for t in tags)
    return MagicMock(returncode=0, stdout=output, stderr="")


@pytest.mark.integration
class TestIsVersionConstraint:
    """Verify PEP 440 constraint detection."""

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
        ],
    )
    def test_detects_constraint(self, rev_spec: str) -> None:
        assert is_version_constraint(rev_spec) is True

    @pytest.mark.parametrize(
        "rev_spec",
        ["main", "refs/tags/1.1.2", "some-branch", "v1.0.0"],
    )
    def test_passthrough_plain_refs(self, rev_spec: str) -> None:
        assert is_version_constraint(rev_spec) is False


@pytest.mark.integration
class TestResolveVersionPassthrough:
    """Verify plain branch/tag refs pass through unchanged."""

    @pytest.mark.parametrize(
        "rev_spec",
        ["main", "v1.0.0", "refs/tags/1.1.2", "my-branch"],
    )
    def test_plain_ref_unchanged(self, rev_spec: str) -> None:
        result = resolve_version("https://example.com/repo.git", rev_spec)
        assert result == rev_spec


@pytest.mark.integration
class TestResolveVersionBareConstraint:
    """Verify bare PEP 440 constraints resolve to the correct version tag."""

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

    def test_wildcard_returns_highest(self) -> None:
        tags = ["refs/tags/1.0.0", "refs/tags/2.0.0", "refs/tags/3.0.0"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version("https://example.com/repo.git", "*")
        assert result == "refs/tags/3.0.0"

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


@pytest.mark.integration
class TestResolveVersionPrefixedConstraint:
    """Verify prefixed constraints resolve against namespaced tags."""

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

    def test_namespaced_prefix_filters_correctly(self) -> None:
        tags = [
            "refs/tags/dev/python/my-lib/1.0.0",
            "refs/tags/dev/python/my-lib/1.2.7",
            "refs/tags/dev/python/other-lib/9.9.9",
        ]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            result = resolve_version(
                "https://example.com/repo.git",
                "refs/tags/dev/python/my-lib/~=1.2.0",
            )
        assert result == "refs/tags/dev/python/my-lib/1.2.7"

    def test_no_tags_under_prefix_exits(self) -> None:
        tags = ["refs/tags/1.0.0"]
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = _mock_ls_remote(tags)
            with pytest.raises(SystemExit):
                resolve_version(
                    "https://example.com/repo.git",
                    "refs/tags/dev/python/missing/~=1.0.0",
                )


@pytest.mark.integration
class TestListTags:
    """Verify git ls-remote tag parsing returns full ref paths."""

    def test_parses_tags_correctly(self) -> None:
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="abc\trefs/tags/1.0.0\ndef\trefs/tags/2.0.0\nghi\trefs/tags/2.0.0^{}\n",
                stderr="",
            )
            tags = _list_tags("https://example.com/repo.git")
        assert tags == ["refs/tags/1.0.0", "refs/tags/2.0.0"]

    def test_excludes_peeled_tag_refs(self) -> None:
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="abc\trefs/tags/1.0.0^{}\n",
                stderr="",
            )
            tags = _list_tags("https://example.com/repo.git")
        assert tags == []

    def test_empty_output_returns_empty_list(self) -> None:
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            tags = _list_tags("https://example.com/repo.git")
        assert tags == []

    def test_git_failure_exits(self) -> None:
        with patch("kanon_cli.version.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="fatal")
            with pytest.raises(SystemExit):
                _list_tags("https://example.com/repo.git")
