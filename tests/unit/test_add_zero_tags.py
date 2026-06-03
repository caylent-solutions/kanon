"""Unit tests for the zero-PEP-440-tags loud-error path in kanon add.

Tests the default-spec error path that fires BEFORE any constraint resolution
when the manifest repo has either zero tags total or zero PEP 440-valid tags.

Spec reference: kanon-list-add-lock-features-spec.md Section 4.2, step 4.

AC-TEST-001
"""

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Spec-verbatim error wording
# ---------------------------------------------------------------------------

_SPEC_ERROR_MSG = (
    "manifest repo has no PEP 440-valid tags; pin to a branch or SHA"
    " explicitly (e.g., 'kanon add foo@main') or ask the catalog author"
    " to publish a release tag."
)


# ---------------------------------------------------------------------------
# Helper: call _resolve_spec with a mocked _list_tags return value
# ---------------------------------------------------------------------------


def _call_resolve_spec(tags: list[str], url: str = "https://example.com/repo.git") -> None:
    """Call _resolve_spec(url, spec=None) with a patched _list_tags result.

    Args:
        tags: The list of tag refs returned by the mocked _list_tags.
        url: The manifest repo URL (used only as a label in error messages).

    Raises:
        SystemExit: Always -- _resolve_spec sys.exit()s on the zero-tags paths.
    """
    from kanon_cli.commands import add as add_mod

    with patch.object(add_mod, "_list_tags", return_value=tags):
        add_mod._resolve_spec(url, spec=None)


# ---------------------------------------------------------------------------
# Parameterised tests: zero-tags-total vs zero-PEP-440-tags
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "tags,subcase",
    [
        ([], "zero-tags-total"),
        (
            ["refs/tags/release-2024", "refs/tags/ops-marker"],
            "zero-pep440-tags",
        ),
    ],
)
class TestResolveSpecZeroTagsError:
    """_resolve_spec raises SystemExit with the spec-verbatim error for both subcases."""

    def test_exits_nonzero(
        self,
        tags: list[str],
        subcase: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exit code is non-zero for both subcases."""
        with pytest.raises(SystemExit) as exc_info:
            _call_resolve_spec(tags)
        assert exc_info.value.code != 0, f"subcase={subcase}: expected non-zero exit, got {exc_info.value.code!r}"

    def test_stderr_contains_spec_verbatim_error(
        self,
        tags: list[str],
        subcase: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Stderr output contains the spec-verbatim error message."""
        with pytest.raises(SystemExit):
            _call_resolve_spec(tags)
        captured = capsys.readouterr()
        assert _SPEC_ERROR_MSG in captured.err, (
            f"subcase={subcase}: spec-verbatim error not found in stderr.\nstderr: {captured.err!r}"
        )


@pytest.mark.unit
class TestResolveSpecZeroPEP440TagsListsSkipped:
    """When tags exist but none are PEP 440-valid, stderr lists skipped tag names."""

    def test_skipped_tag_names_appear_in_stderr(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Non-PEP-440 tag names are listed in stderr (first up to 10)."""
        non_pep440_tags = [
            "refs/tags/release-2024",
            "refs/tags/ops-marker",
        ]
        with pytest.raises(SystemExit):
            _call_resolve_spec(non_pep440_tags)
        captured = capsys.readouterr()
        assert "release-2024" in captured.err, f"expected 'release-2024' in stderr, got: {captured.err!r}"
        assert "ops-marker" in captured.err, f"expected 'ops-marker' in stderr, got: {captured.err!r}"

    def test_at_most_10_skipped_tags_listed(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """At most 10 non-PEP-440 tag names are listed, even when more exist."""
        many_non_pep440 = [f"refs/tags/bad-tag-{i:02d}" for i in range(15)]
        with pytest.raises(SystemExit):
            _call_resolve_spec(many_non_pep440)
        captured = capsys.readouterr()
        # Verify the spec-verbatim error is there
        assert _SPEC_ERROR_MSG in captured.err, f"spec-verbatim error not found in stderr: {captured.err!r}"
        # Count how many "bad-tag-" occurrences appear in the skipped list
        listed_count = captured.err.count("bad-tag-")
        assert listed_count <= 10, f"expected at most 10 skipped tags listed, found {listed_count}"


@pytest.mark.unit
class TestResolveSpecExplicitSpecBypassesDefaultError:
    """When an explicit @<spec> is supplied, _resolve_spec delegates to resolve_version.

    The default-spec zero-tags error MUST NOT fire when spec is a non-None string.
    AC-FUNC-005.
    """

    def test_explicit_spec_does_not_call_list_tags(self) -> None:
        """_resolve_spec with a non-None spec calls resolve_version, not _list_tags."""
        from kanon_cli.commands import add as add_mod

        with (
            patch.object(add_mod, "_list_tags") as mock_list_tags,
            patch.object(add_mod, "resolve_version", return_value="refs/tags/1.0.0"),
        ):
            result = add_mod._resolve_spec("https://example.com/repo.git", spec="==1.0.0")
        mock_list_tags.assert_not_called()
        assert result == "refs/tags/1.0.0"
