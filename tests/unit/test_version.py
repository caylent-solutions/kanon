"""Tests for fuzzy version resolution."""

from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.version import (
    RevisionShape,
    _classify_revision_shape,
    _format_zero_pep440_tags_error,
    _is_bare_pep440_version,
    _list_branch_head,
    _list_tags,
    _normalize_bare_semver_to_tag,
    _resolve_constraint_from_tags,
    _resolve_symref_default_branch,
    _truncate_sha,
    is_pep440_version,
    is_version_constraint,
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


@pytest.mark.unit
class TestIsPep440VersionSharedGrammar:
    """AC-27: the validator and resolver share one PEP 440 grammar definition.

    ``is_pep440_version`` is the single ``packaging.version.Version`` parse used
    by both ``kanon_cli.version`` (the resolver) and
    ``kanon_cli.core.marketplace_validator`` (the validator), so the grammar is
    defined once (DRY) rather than as a duplicated ``\\d+\\.\\d+\\.\\d+`` regex.
    """

    @pytest.mark.parametrize(
        "component",
        [
            "1",
            "1.2",
            "1.0.0",
            "1.2.0a1",
            "1.0.0rc1",
            "1.0.0b3",
            "2024.6",
            "1!2.0.0",
            "1.0.0.post1",
            "1.0.0.dev0",
            "1.0.0+local.build",
            "v1.0.0",
        ],
    )
    def test_accepts_full_pep440_grammar(self, component: str) -> None:
        assert is_pep440_version(component) is True

    @pytest.mark.parametrize(
        "component",
        ["1.2.x", "release-1.0.0", "not-a-version", "", "main"],
    )
    def test_rejects_non_pep440(self, component: str) -> None:
        assert is_pep440_version(component) is False

    def test_bare_helper_delegates_to_shared_grammar(self) -> None:
        """``_is_bare_pep440_version`` reuses ``is_pep440_version`` after the
        no-slash guard, so the two never diverge on a slashless token."""
        assert _is_bare_pep440_version("1.2.0a1") is True
        assert _is_bare_pep440_version("1.2.0a1") == is_pep440_version("1.2.0a1")
        # The slash guard rejects monorepo-prefixed inputs the shared parse alone
        # would otherwise mis-handle.
        assert _is_bare_pep440_version("subpackage/1.0.0") is False

    def test_validator_and_resolver_agree_on_each_input(self) -> None:
        """The validator's tag path and the resolver share is_pep440_version.

        For the same slashless version token, the validator's acceptance of a
        ``refs/tags/ex/<token>`` tag matches ``is_pep440_version(token)`` and
        the resolver's bare-version normalization.
        """
        from kanon_cli.core.marketplace_validator import _is_exact_tag_revision

        for token in ["1", "1.2", "1.2.0a1", "2024.6", "1.2.x", "not-a-version"]:
            shared = is_pep440_version(token)
            validator = _is_exact_tag_revision(f"refs/tags/ex/{token}")
            resolver_normalized = _normalize_bare_semver_to_tag(token) == f"refs/tags/{token}"
            assert validator == shared, f"validator disagrees with shared grammar on {token!r}"
            assert resolver_normalized == shared, f"resolver disagrees with shared grammar on {token!r}"


@pytest.mark.unit
class TestResolveConstraintFromTagsLoudError:
    """AC-FUNC-001 through AC-FUNC-007, AC-TEST-001, AC-TEST-002, AC-TEST-003.

    Verify that _resolve_constraint_from_tags emits a loud, enumerated error
    message when candidates exist under the prefix but none parse as PEP 440.

    Spec source: kanon-list-add-lock-features-spec.md Section 0.4 and
    Section 13 decision 14.
    """

    def _make_tags(self, prefix: str, names: list[str]) -> list[str]:
        """Build full tag refs under a given prefix."""
        return [f"refs/tags/{prefix}/{name}" for name in names]

    @pytest.mark.parametrize(
        ("skipped_names", "constraint", "prefix", "expected_count"),
        [
            # AC-TEST-001: 1 skipped tag
            (["release-2024"], "==1.0.0", "mylib", 1),
            # AC-TEST-001: 5 skipped tags
            (
                ["release-a", "release-b", "release-c", "release-d", "release-e"],
                "==1.0.0",
                "mylib",
                5,
            ),
            # AC-TEST-001: exactly 10 skipped tags (no suffix line)
            (
                [f"release-{i:02d}" for i in range(10)],
                "==1.0.0",
                "mylib",
                10,
            ),
        ],
        ids=["one-skipped", "five-skipped", "ten-skipped"],
    )
    def test_loud_error_message_structure(
        self,
        skipped_names: list[str],
        constraint: str,
        prefix: str,
        expected_count: int,
    ) -> None:
        """AC-FUNC-001, AC-FUNC-002, AC-FUNC-003: message structure for N<=10 skipped."""
        tags = self._make_tags(prefix, skipped_names)
        revision = f"refs/tags/{prefix}/{constraint}"

        with pytest.raises(ValueError) as exc_info:
            _resolve_constraint_from_tags(revision, tags)

        msg = str(exc_info.value)
        assert msg.startswith(f"ERROR: No PEP 440-parseable version tags found under 'refs/tags/{prefix}'."), (
            f"Message did not start with expected header. Got: {msg!r}"
        )
        assert f"Skipped {expected_count} tag(s) whose last path component is not a valid PEP 440 version:" in msg, (
            f"Missing skipped-count line in: {msg!r}"
        )
        # All skipped names should appear as bullet lines
        for name in skipped_names:
            assert f"  - refs/tags/{prefix}/{name}" in msg, f"Missing bullet for {name!r} in: {msg!r}"
        # No truncation suffix when N <= 10
        assert "showing first 10 of" not in msg, f"Unexpected truncation suffix when N={expected_count}: {msg!r}"

    def test_loud_error_eleven_skipped_has_suffix(self) -> None:
        """AC-FUNC-004, AC-TEST-001: exactly 11 skipped tags shows suffix line."""
        skipped_names = [f"release-{i:02d}" for i in range(11)]
        tags = self._make_tags("mylib", skipped_names)
        revision = "refs/tags/mylib/==1.0.0"

        with pytest.raises(ValueError) as exc_info:
            _resolve_constraint_from_tags(revision, tags)

        msg = str(exc_info.value)
        assert "... (showing first 10 of 11)" in msg, f"Expected truncation suffix for 11 skipped tags. Got: {msg!r}"
        # Only 10 bullets should appear
        bullet_lines = [line for line in msg.splitlines() if line.startswith("  - ")]
        assert len(bullet_lines) == 10, f"Expected 10 bullet lines for 11 skipped tags, got {len(bullet_lines)}"

    def test_zero_candidates_preserves_narrow_message(self) -> None:
        """AC-FUNC-006, AC-TEST-001: zero candidates under prefix keeps original message."""
        # Tags exist, but none are under the requested prefix
        tags = ["refs/tags/other/1.0.0", "refs/tags/other/2.0.0"]
        revision = "refs/tags/mylib/==1.0.0"

        with pytest.raises(ValueError) as exc_info:
            _resolve_constraint_from_tags(revision, tags)

        msg = str(exc_info.value)
        assert "No tags found under prefix" in msg, f"Expected narrow no-candidates message. Got: {msg!r}"
        assert "ERROR: No PEP 440-parseable" not in msg, (
            f"Loud format should NOT fire for zero-candidate case. Got: {msg!r}"
        )

    def test_bullet_ordering_is_deterministic_regardless_of_input_order(self) -> None:
        """AC-TEST-002: bullet list is sorted deterministically.

        Passes the same set of tag names in two different orderings and
        asserts that the resulting error message is identical in both cases.
        """
        names_forward = ["release-b", "release-a", "release-c"]
        names_reversed = list(reversed(names_forward))
        prefix = "mylib"
        revision = f"refs/tags/{prefix}/==1.0.0"

        tags_forward = self._make_tags(prefix, names_forward)
        tags_reversed = self._make_tags(prefix, names_reversed)

        with pytest.raises(ValueError) as exc_forward:
            _resolve_constraint_from_tags(revision, tags_forward)
        with pytest.raises(ValueError) as exc_reversed:
            _resolve_constraint_from_tags(revision, tags_reversed)

        assert str(exc_forward.value) == str(exc_reversed.value), (
            "Error message differs based on input ordering -- must be deterministic"
        )

    def test_remediation_pointer_contains_audit_command(self) -> None:
        """AC-TEST-003, AC-FUNC-005: message contains exact remediation command."""
        tags = self._make_tags("mylib", ["release-2024"])
        revision = "refs/tags/mylib/==1.0.0"

        with pytest.raises(ValueError) as exc_info:
            _resolve_constraint_from_tags(revision, tags)

        msg = str(exc_info.value)
        assert "kanon catalog audit --check tag-format" in msg, (
            f"Remediation pointer missing from error message. Got: {msg!r}"
        )

    def test_format_zero_pep440_tags_error_helper_direct(self) -> None:
        """AC-FUNC-001 through AC-FUNC-005: exercise the private helper directly.

        The helper must be independently testable per SRP/DRY requirements.
        """
        skipped = ["refs/tags/mylib/release-a", "refs/tags/mylib/release-b"]
        msg = _format_zero_pep440_tags_error("refs/tags/mylib", skipped)
        assert msg.startswith("ERROR: No PEP 440-parseable version tags found under 'refs/tags/mylib'.")
        assert "Skipped 2 tag(s)" in msg
        assert "  - refs/tags/mylib/release-a" in msg
        assert "  - refs/tags/mylib/release-b" in msg
        assert "kanon catalog audit --check tag-format" in msg


# ---------------------------------------------------------------------------
# RevisionShape enum tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRevisionShapeEnum:
    """Verify the RevisionShape enum has the expected members and values."""

    def test_has_tag_member(self) -> None:
        """RevisionShape.TAG member exists."""
        assert RevisionShape.TAG is not None

    def test_has_branch_member(self) -> None:
        """RevisionShape.BRANCH member exists."""
        assert RevisionShape.BRANCH is not None

    def test_has_sha_member(self) -> None:
        """RevisionShape.SHA member exists."""
        assert RevisionShape.SHA is not None

    def test_members_are_distinct(self) -> None:
        """TAG, BRANCH, and SHA are distinct enum values."""
        assert RevisionShape.TAG != RevisionShape.BRANCH
        assert RevisionShape.TAG != RevisionShape.SHA
        assert RevisionShape.BRANCH != RevisionShape.SHA

    def test_tag_value_is_string(self) -> None:
        """RevisionShape.TAG has a string value."""
        assert isinstance(RevisionShape.TAG.value, str)


# ---------------------------------------------------------------------------
# _classify_revision_shape tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "revision, expected_shape",
    [
        # SHA-pinned: exactly 40 hex characters
        ("a" * 40, RevisionShape.SHA),
        ("0" * 40, RevisionShape.SHA),
        ("abcdef1234567890abcdef1234567890abcdef12", RevisionShape.SHA),
        # SHA-pinned: exactly 64 hex characters
        ("b" * 64, RevisionShape.SHA),
        ("f" * 64, RevisionShape.SHA),
        # Tag-pinned: PEP 440 constraint operators
        (">=1.0.0", RevisionShape.TAG),
        ("~=1.0.0", RevisionShape.TAG),
        ("<=2.0.0", RevisionShape.TAG),
        ("==1.0.0", RevisionShape.TAG),
        ("!=1.0.0", RevisionShape.TAG),
        (">1.0.0", RevisionShape.TAG),
        ("<2.0.0", RevisionShape.TAG),
        (">=1.0.0,<2.0.0", RevisionShape.TAG),
        ("*", RevisionShape.TAG),
        ("latest", RevisionShape.TAG),
        # Tag-pinned: refs/tags/ prefix
        ("refs/tags/1.0.0", RevisionShape.TAG),
        ("refs/tags/>=1.0.0", RevisionShape.TAG),
        ("refs/tags/~=1.0.0", RevisionShape.TAG),
        # Branch-pinned: plain branch names
        ("main", RevisionShape.BRANCH),
        ("develop", RevisionShape.BRANCH),
        ("feature/foo", RevisionShape.BRANCH),
        ("release/v1", RevisionShape.BRANCH),
        ("my-branch", RevisionShape.BRANCH),
    ],
)
class TestClassifyRevisionShapeVersion:
    def test_classification(self, revision: str, expected_shape: RevisionShape) -> None:
        result = _classify_revision_shape(revision)
        assert result == expected_shape, (
            f"_classify_revision_shape({revision!r}) = {result!r}, expected {expected_shape!r}"
        )


# ---------------------------------------------------------------------------
# _truncate_sha tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "full_sha, expected",
    [
        ("abcdef1234567890abcdef1234567890abcdef12", "abcdef123456"),
        ("0" * 40, "0" * 12),
        ("f" * 64, "f" * 12),
        ("1234567890abcdef" + "0" * 24, "1234567890ab"),
    ],
)
class TestTruncateSha:
    def test_truncation(self, full_sha: str, expected: str) -> None:
        result = _truncate_sha(full_sha)
        assert result == expected, f"_truncate_sha({full_sha!r}) = {result!r}, expected {expected!r}"
        assert len(result) == 12


# ---------------------------------------------------------------------------
# _list_branch_head tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListBranchHead:
    """Unit tests for _list_branch_head in version.py."""

    def test_returns_sha_for_matching_branch(self) -> None:
        """Successful lookup returns the full SHA string."""
        expected_sha = "abcdef1234567890abcdef1234567890abcdef12"
        mock_result = MagicMock(
            returncode=0,
            stdout=f"{expected_sha}\trefs/heads/main\n",
            stderr="",
        )
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            sha = _list_branch_head("file:///repo", "main")
        assert sha == expected_sha

    def test_multiple_refs_returns_correct_branch(self) -> None:
        """When multiple refs are returned, only the matching branch SHA is returned."""
        sha_main = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        sha_other = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        mock_result = MagicMock(
            returncode=0,
            stdout=(f"{sha_other}\trefs/heads/other\n{sha_main}\trefs/heads/main\n"),
            stderr="",
        )
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            sha = _list_branch_head("file:///repo", "main")
        assert sha == sha_main

    def test_nonzero_returncode_raises_runtime_error(self) -> None:
        """Non-zero git exit code raises RuntimeError."""
        mock_result = MagicMock(returncode=128, stdout="", stderr="fatal: not a repository")
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="ERROR:"):
                _list_branch_head("file:///repo", "main")

    def test_nonzero_returncode_error_includes_url(self) -> None:
        """RuntimeError message includes the repository URL."""
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError) as exc_info:
                _list_branch_head("https://example.com/repo.git", "main")
        assert "https://example.com/repo.git" in str(exc_info.value)

    def test_branch_not_found_raises_value_error(self) -> None:
        """Empty stdout raises ValueError when branch is not found."""
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(ValueError, match="not found on remote"):
                _list_branch_head("file:///repo", "missing-branch")

    def test_branch_not_found_error_includes_branch_name(self) -> None:
        """ValueError message includes the branch name."""
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(ValueError) as exc_info:
                _list_branch_head("file:///repo", "my-branch")
        assert "my-branch" in str(exc_info.value)

    def test_git_not_found_raises_runtime_error(self) -> None:
        """FileNotFoundError when git is absent raises RuntimeError."""
        with patch(
            "kanon_cli.version.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        ):
            with pytest.raises(RuntimeError, match="ERROR:"):
                _list_branch_head("file:///repo", "main")

    def test_git_not_found_error_mentions_git(self) -> None:
        """RuntimeError message for missing git binary mentions 'git'."""
        with patch(
            "kanon_cli.version.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                _list_branch_head("file:///repo", "main")
        assert "git" in str(exc_info.value).lower()

    def test_empty_lines_in_output_are_skipped(self) -> None:
        """Empty lines in git ls-remote output are skipped without error."""
        expected_sha = "cccccccccccccccccccccccccccccccccccccccc"
        mock_result = MagicMock(
            returncode=0,
            stdout=f"\n{expected_sha}\trefs/heads/main\n\n",
            stderr="",
        )
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            sha = _list_branch_head("file:///repo", "main")
        assert sha == expected_sha

    def test_lines_without_tab_are_skipped(self) -> None:
        """Lines without a tab separator are skipped; ValueError if no match found."""
        mock_result = MagicMock(
            returncode=0,
            stdout="malformed-line-no-tab\n",
            stderr="",
        )
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(ValueError, match="not found on remote"):
                _list_branch_head("file:///repo", "main")


# ---------------------------------------------------------------------------
# _resolve_symref_default_branch tests (AC-15: auto via git ls-remote --symref)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveSymrefDefaultBranch:
    """Unit tests for _resolve_symref_default_branch in version.py."""

    @pytest.mark.parametrize(
        "advertised_branch",
        ["main", "master", "develop", "trunk"],
    )
    def test_parses_advertised_head_symref_branch(self, advertised_branch: str) -> None:
        """The bare branch from the 'ref: refs/heads/<branch>\\tHEAD' line is returned."""
        symref_line = f"ref: refs/heads/{advertised_branch}\tHEAD"
        sha_line = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\tHEAD"
        stdout = f"{symref_line}\n{sha_line}\n"
        with patch(
            "kanon_cli.version.run_git_ls_remote",
            return_value=(0, stdout, ""),
        ):
            result = _resolve_symref_default_branch("file:///repo")
        assert result == advertised_branch

    def test_routes_through_shared_runner_with_symref_flag(self) -> None:
        """The command issued through the shared runner includes --symref and HEAD."""
        stdout = "ref: refs/heads/main\tHEAD\n"
        with patch(
            "kanon_cli.version.run_git_ls_remote",
            return_value=(0, stdout, ""),
        ) as mock_runner:
            _resolve_symref_default_branch("https://example.com/repo.git")
        called_cmd = mock_runner.call_args.args[0]
        assert called_cmd == ["git", "ls-remote", "--symref", "https://example.com/repo.git", "HEAD"]

    def test_no_head_symref_advertised_returns_none(self) -> None:
        """When no 'ref: refs/heads/...' line is advertised, None is returned."""
        # A remote that only advertises the HEAD SHA (no symref line).
        stdout = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\tHEAD\n"
        with patch(
            "kanon_cli.version.run_git_ls_remote",
            return_value=(0, stdout, ""),
        ):
            assert _resolve_symref_default_branch("file:///repo") is None

    def test_symref_to_non_heads_ref_returns_none(self) -> None:
        """A symref that does not target refs/heads/ is not a default branch -> None."""
        stdout = "ref: refs/remotes/origin/main\tHEAD\n"
        with patch(
            "kanon_cli.version.run_git_ls_remote",
            return_value=(0, stdout, ""),
        ):
            assert _resolve_symref_default_branch("file:///repo") is None

    def test_nonzero_returncode_raises_runtime_error(self) -> None:
        """A non-zero git exit raises RuntimeError naming the URL."""
        with patch(
            "kanon_cli.version.run_git_ls_remote",
            return_value=(128, "", "fatal: repository not found"),
        ):
            with pytest.raises(RuntimeError, match="git ls-remote --symref failed"):
                _resolve_symref_default_branch("file:///missing")
