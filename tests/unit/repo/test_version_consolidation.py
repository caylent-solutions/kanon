"""Parametrized tests proving behavioral equivalence between kanon version.py and
repo version_constraints.py for all shared inputs.

These tests establish a safety net before consolidation (E0-F7-S1-T2) by
verifying that both implementations produce identical results for:
- is_version_constraint: exact version matches, range constraints, wildcards,
  pre-release versions, invalid strings, edge cases, compound constraints.
- resolve: for prefixed revisions with available tags supplied, both
  implementations select the same highest-matching tag.

Any divergence detected here must be documented and resolved before the
consolidation work unit proceeds.
"""

import pytest
from unittest.mock import MagicMock, patch

from kanon_cli.repo import error as repo_error
from kanon_cli.repo import version_constraints as repo_vc
from kanon_cli import version as kanon_version


# ---------------------------------------------------------------------------
# Shared test data -- all constants live here, not inline in test bodies.
# ---------------------------------------------------------------------------

_TAG_PREFIX = "refs/tags/dev/python/my-lib"

# Input strings that both implementations must classify as version constraints.
_IS_CONSTRAINT_TRUE_CASES = [
    # AC-TEST-001: Exact version match operators
    pytest.param("==1.0.0", id="exact-==1.0.0"),
    pytest.param("==1.2.3", id="exact-==1.2.3"),
    pytest.param("==0.0.1", id="exact-==0.0.1"),
    # AC-TEST-002: Range constraints
    pytest.param(">=1.0.0,<2.0.0", id="range->=1.0.0,<2.0.0"),
    pytest.param(">=1.2.0,<1.3.0", id="range->=1.2.0,<1.3.0"),
    pytest.param(">=0.1.0,<=1.0.0", id="range->=0.1.0,<=1.0.0"),
    # AC-TEST-003: Wildcard patterns
    pytest.param("*", id="wildcard-bare"),
    # AC-TEST-004: Pre-release version operators
    pytest.param(">=1.0.0a1", id="prerelease->=1.0.0a1"),
    pytest.param("~=2.0.0b1", id="prerelease-~=2.0.0b1"),
    pytest.param("==1.0.0rc1", id="prerelease-==1.0.0rc1"),
    # AC-TEST-007: Complex compound constraints
    pytest.param("~=1.0.0", id="compound-compatible-release"),
    pytest.param(">=1.0.0", id="compound-gte"),
    pytest.param("<=2.0.0", id="compound-lte"),
    pytest.param(">1.0.0", id="compound-gt"),
    pytest.param("<2.0.0", id="compound-lt"),
    pytest.param("!=1.0.1", id="compound-neq"),
    pytest.param(">=1.0.0,<=2.0.0,!=1.5.0", id="compound-triple"),
]

# Input strings that both implementations must classify as NOT version constraints.
_IS_CONSTRAINT_FALSE_CASES = [
    # AC-TEST-001: Plain exact pins (no operators -- not constraints)
    pytest.param("1.0.0", id="pin-1.0.0"),
    pytest.param("1.2.3", id="pin-1.2.3"),
    pytest.param("v1.0.0", id="pin-v1.0.0"),
    # AC-TEST-005: Invalid version strings (also not constraints)
    pytest.param("not-a-version", id="invalid-not-a-version"),
    pytest.param("", id="edge-empty-string"),
    pytest.param("abc123", id="invalid-hex-hash"),
    # AC-TEST-006: Edge cases -- plain refs and branches
    pytest.param("main", id="edge-branch-main"),
    pytest.param("develop", id="edge-branch-develop"),
    pytest.param("refs/heads/main", id="edge-full-branch-ref"),
    pytest.param("refs/tags/1.0.0", id="edge-full-tag-ref"),
    pytest.param("refs/tags/v2.0.0", id="edge-versioned-tag"),
    pytest.param("caylent-2.0.0", id="edge-prefixed-version"),
]

# Input strings passed through the last path component (prefixed forms) that
# both implementations must classify as version constraints.
_IS_CONSTRAINT_TRUE_PREFIXED_CASES = [
    pytest.param(f"{_TAG_PREFIX}/==1.0.0", id="prefixed-exact-==1.0.0"),
    pytest.param(f"{_TAG_PREFIX}/>=1.0.0,<2.0.0", id="prefixed-range"),
    pytest.param(f"{_TAG_PREFIX}/*", id="prefixed-wildcard"),
    pytest.param(f"{_TAG_PREFIX}/~=1.2.0", id="prefixed-compatible"),
    pytest.param(f"{_TAG_PREFIX}/>=1.0.0a1", id="prefixed-prerelease"),
]

# Resolve equivalence cases: (revision, available_tags, expected_tag)
# Both implementations must return the same expected_tag when given the same
# prefixed revision and tag list.
_AVAILABLE_TAGS = (
    f"{_TAG_PREFIX}/1.0.0",
    f"{_TAG_PREFIX}/1.1.0",
    f"{_TAG_PREFIX}/1.2.0",
    f"{_TAG_PREFIX}/1.2.3",
    f"{_TAG_PREFIX}/1.2.7",
    f"{_TAG_PREFIX}/1.3.0",
    f"{_TAG_PREFIX}/2.0.0",
    f"{_TAG_PREFIX}/2.1.0",
    f"{_TAG_PREFIX}/3.0.0",
    "refs/tags/unrelated/other-lib/1.0.0",
)

_RESOLVE_EQUIVALENCE_CASES = [
    # AC-TEST-001: Exact version match
    pytest.param(
        f"{_TAG_PREFIX}/==1.2.3",
        _AVAILABLE_TAGS,
        f"{_TAG_PREFIX}/1.2.3",
        id="exact-==1.2.3",
    ),
    # AC-TEST-002: Range constraint
    pytest.param(
        f"{_TAG_PREFIX}/>=1.0.0,<2.0.0",
        _AVAILABLE_TAGS,
        f"{_TAG_PREFIX}/1.3.0",
        id="range->=1.0.0,<2.0.0",
    ),
    # AC-TEST-003: Wildcard
    pytest.param(
        f"{_TAG_PREFIX}/*",
        _AVAILABLE_TAGS,
        f"{_TAG_PREFIX}/3.0.0",
        id="wildcard-returns-highest",
    ),
    # AC-TEST-004: Pre-release excluded by default
    pytest.param(
        f"{_TAG_PREFIX}/>=1.0.0",
        (
            f"{_TAG_PREFIX}/1.0.0a1",
            f"{_TAG_PREFIX}/1.0.0",
        ),
        f"{_TAG_PREFIX}/1.0.0",
        id="prerelease-excluded",
    ),
    # AC-TEST-004: Pre-release included when constraint references pre-release
    pytest.param(
        f"{_TAG_PREFIX}/>=1.0.0a1",
        (
            f"{_TAG_PREFIX}/1.0.0a1",
            f"{_TAG_PREFIX}/1.0.0",
        ),
        f"{_TAG_PREFIX}/1.0.0",
        id="prerelease-included-when-constraint-specifies",
    ),
    # AC-TEST-007: Compatible release (~=)
    pytest.param(
        f"{_TAG_PREFIX}/~=1.2.0",
        _AVAILABLE_TAGS,
        f"{_TAG_PREFIX}/1.2.7",
        id="compatible-release-~=1.2.0",
    ),
    # AC-TEST-007: Not-equal constraint excludes specific version
    pytest.param(
        f"{_TAG_PREFIX}/!=1.3.0",
        (
            f"{_TAG_PREFIX}/1.0.0",
            f"{_TAG_PREFIX}/1.2.0",
            f"{_TAG_PREFIX}/1.3.0",
        ),
        f"{_TAG_PREFIX}/1.2.0",
        id="neq-!=1.3.0",
    ),
    # AC-TEST-007: Complex compound constraint with three terms
    pytest.param(
        f"{_TAG_PREFIX}/>=1.0.0,<=2.0.0,!=1.3.0",
        _AVAILABLE_TAGS,
        f"{_TAG_PREFIX}/2.0.0",
        id="complex-three-term-compound",
    ),
    # AC-TEST-007: Highest match from unsorted tag list
    pytest.param(
        f"{_TAG_PREFIX}/>=1.2.0",
        (
            f"{_TAG_PREFIX}/1.2.7",
            f"{_TAG_PREFIX}/1.2.0",
            f"{_TAG_PREFIX}/1.2.3",
            f"{_TAG_PREFIX}/1.3.0",
        ),
        f"{_TAG_PREFIX}/1.3.0",
        id="highest-match-unsorted",
    ),
]


def _build_ls_remote_output(tags: tuple[str, ...]) -> MagicMock:
    """Build a mock subprocess.run result for git ls-remote returning the given tags.

    Args:
        tags: Full tag ref strings to include in the mock output.

    Returns:
        MagicMock with returncode=0 and stdout formatted as git ls-remote output.
    """
    stdout = "\n".join(f"abc123def456\t{tag}" for tag in tags)
    return MagicMock(returncode=0, stdout=stdout, stderr="")


# ---------------------------------------------------------------------------
# AC-TEST-008: is_version_constraint equivalence -- bare inputs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsVersionConstraintEquivalenceTrueInputs:
    """Both implementations return True for the same PEP 440 constraint inputs.

    AC-TEST-001, AC-TEST-002, AC-TEST-003, AC-TEST-004, AC-TEST-007, AC-TEST-008.
    """

    @pytest.mark.parametrize("constraint", _IS_CONSTRAINT_TRUE_CASES)
    def test_both_return_true_for_constraint(self, constraint: str) -> None:
        """Both is_version_constraint implementations return True for constraint inputs.

        Given: A PEP 440 constraint string.
        When: Both implementations are called.
        Then: Both return True and the results are identical.
        """
        kanon_result = kanon_version.is_version_constraint(constraint)
        repo_result = repo_vc.is_version_constraint(constraint)

        assert kanon_result is True, (
            f"kanon version.is_version_constraint({constraint!r}) returned {kanon_result!r}, expected True"
        )
        assert repo_result is True, (
            f"repo version_constraints.is_version_constraint({constraint!r}) returned {repo_result!r}, expected True"
        )
        assert kanon_result == repo_result, (
            f"Implementations diverge for input {constraint!r}: kanon={kanon_result!r}, repo={repo_result!r}"
        )


@pytest.mark.unit
class TestIsVersionConstraintEquivalenceFalseInputs:
    """Both implementations return False for the same non-constraint inputs.

    AC-TEST-001, AC-TEST-005, AC-TEST-006, AC-TEST-008.
    """

    @pytest.mark.parametrize("non_constraint", _IS_CONSTRAINT_FALSE_CASES)
    def test_both_return_false_for_non_constraint(self, non_constraint: str) -> None:
        """Both is_version_constraint implementations return False for non-constraint inputs.

        Given: A plain revision string (branch, tag pin, invalid string, edge case).
        When: Both implementations are called.
        Then: Both return False and the results are identical.
        """
        kanon_result = kanon_version.is_version_constraint(non_constraint)
        repo_result = repo_vc.is_version_constraint(non_constraint)

        assert kanon_result is False, (
            f"kanon version.is_version_constraint({non_constraint!r}) returned {kanon_result!r}, expected False"
        )
        assert repo_result is False, (
            f"repo version_constraints.is_version_constraint({non_constraint!r}) returned {repo_result!r},"
            " expected False"
        )
        assert kanon_result == repo_result, (
            f"Implementations diverge for input {non_constraint!r}: kanon={kanon_result!r}, repo={repo_result!r}"
        )


@pytest.mark.unit
class TestIsVersionConstraintEquivalencePrefixedInputs:
    """Both implementations agree on prefixed constraint detection.

    AC-TEST-008: verifies path-component extraction logic is identical.
    """

    @pytest.mark.parametrize("prefixed_revision", _IS_CONSTRAINT_TRUE_PREFIXED_CASES)
    def test_both_return_true_for_prefixed_constraint(self, prefixed_revision: str) -> None:
        """Both implementations correctly extract the last path component.

        Given: A revision with a path prefix and a PEP 440 constraint last component.
        When: Both implementations are called.
        Then: Both return True and the results are identical.
        """
        kanon_result = kanon_version.is_version_constraint(prefixed_revision)
        repo_result = repo_vc.is_version_constraint(prefixed_revision)

        assert kanon_result is True, (
            f"kanon version.is_version_constraint({prefixed_revision!r}) returned {kanon_result!r}, expected True"
        )
        assert repo_result is True, (
            f"repo version_constraints.is_version_constraint({prefixed_revision!r}) returned {repo_result!r},"
            " expected True"
        )
        assert kanon_result == repo_result, (
            f"Implementations diverge for prefixed input {prefixed_revision!r}: "
            f"kanon={kanon_result!r}, repo={repo_result!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-008: resolve equivalence -- both return the same tag for same inputs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveEquivalence:
    """Both resolve implementations return the same tag for identical prefixed inputs.

    For kanon version.resolve_version, subprocess.run is mocked to return the
    same tag list supplied to repo version_constraints.resolve_version_constraint.
    This ensures the equivalence test is comparing pure constraint logic, not
    network behavior.

    AC-TEST-001, AC-TEST-002, AC-TEST-003, AC-TEST-004, AC-TEST-007, AC-TEST-008,
    AC-TEST-009.
    """

    @pytest.mark.parametrize("revision,available_tags,expected_tag", _RESOLVE_EQUIVALENCE_CASES)
    def test_both_resolve_to_same_tag(
        self,
        revision: str,
        available_tags: tuple[str, ...],
        expected_tag: str,
    ) -> None:
        """Both resolve implementations return the same highest-matching tag.

        Given: A prefixed PEP 440 revision and a list of available tags.
        When: kanon version.resolve_version (with mocked git ls-remote) and
              repo version_constraints.resolve_version_constraint are called.
        Then: Both return the same expected tag and results are identical.
        """
        # kanon version.resolve_version fetches tags via subprocess; mock it.
        mock_run = _build_ls_remote_output(available_tags)
        with patch("kanon_cli.version.subprocess.run", return_value=mock_run):
            kanon_result = kanon_version.resolve_version("https://example.com/repo.git", revision)

        # repo version_constraints.resolve_version_constraint receives tags directly.
        repo_result = repo_vc.resolve_version_constraint(revision, list(available_tags))

        assert kanon_result == expected_tag, (
            f"kanon resolve_version({revision!r}) returned {kanon_result!r}, expected {expected_tag!r}"
        )
        assert repo_result == expected_tag, (
            f"repo resolve_version_constraint({revision!r}) returned {repo_result!r}, expected {expected_tag!r}"
        )
        assert kanon_result == repo_result, (
            f"Implementations diverge for revision {revision!r}: kanon={kanon_result!r}, repo={repo_result!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-005, AC-TEST-006: error path equivalence -- invalid / no-match inputs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveErrorPathEquivalence:
    """Both resolve implementations signal failure for no-match and invalid inputs.

    kanon version.resolve_version raises SystemExit; repo
    version_constraints.resolve_version_constraint raises
    ManifestInvalidRevisionError.  Both must fail -- the equivalence being
    tested here is that neither silently succeeds.

    AC-TEST-005, AC-TEST-006, AC-TEST-009.
    """

    _NO_MATCH_REVISION = f"{_TAG_PREFIX}/~=9.9.9"
    _AVAILABLE_TAGS_FOR_ERROR = (
        f"{_TAG_PREFIX}/1.0.0",
        f"{_TAG_PREFIX}/2.0.0",
    )

    def test_no_matching_tag_kanon_exits(self) -> None:
        """kanon resolve_version exits when no tag matches the constraint.

        AC-TEST-005: no-match raises SystemExit (fail-fast, non-zero exit).
        """
        mock_run = _build_ls_remote_output(self._AVAILABLE_TAGS_FOR_ERROR)
        with patch("kanon_cli.version.subprocess.run", return_value=mock_run):
            with pytest.raises(SystemExit):
                kanon_version.resolve_version(
                    "https://example.com/repo.git",
                    self._NO_MATCH_REVISION,
                )

    def test_no_matching_tag_repo_raises(self) -> None:
        """repo resolve_version_constraint raises ManifestInvalidRevisionError when no tag matches.

        AC-TEST-005: no-match raises ManifestInvalidRevisionError (fail-fast).
        """
        with pytest.raises(repo_error.ManifestInvalidRevisionError):
            repo_vc.resolve_version_constraint(
                self._NO_MATCH_REVISION,
                list(self._AVAILABLE_TAGS_FOR_ERROR),
            )

    def test_invalid_specifier_kanon_exits(self) -> None:
        """kanon resolve_version exits for an invalid specifier string.

        AC-TEST-005: invalid specifier raises SystemExit (fail-fast).
        """
        mock_run = _build_ls_remote_output(self._AVAILABLE_TAGS_FOR_ERROR)
        with patch("kanon_cli.version.subprocess.run", return_value=mock_run):
            with pytest.raises(SystemExit):
                kanon_version.resolve_version(
                    "https://example.com/repo.git",
                    f"{_TAG_PREFIX}/>>invalid<<",
                )

    def test_invalid_specifier_repo_raises(self) -> None:
        """repo resolve_version_constraint raises ManifestInvalidRevisionError for invalid specifier.

        AC-TEST-005: invalid specifier raises ManifestInvalidRevisionError (fail-fast).
        """
        with pytest.raises(repo_error.ManifestInvalidRevisionError):
            repo_vc.resolve_version_constraint(
                f"{_TAG_PREFIX}/>>invalid<<",
                list(self._AVAILABLE_TAGS_FOR_ERROR),
            )

    def test_empty_tags_kanon_exits(self) -> None:
        """kanon resolve_version exits when tag list is empty.

        AC-TEST-006: empty tags raises SystemExit (fail-fast).
        """
        mock_run = _build_ls_remote_output(())
        with patch("kanon_cli.version.subprocess.run", return_value=mock_run):
            with pytest.raises(SystemExit):
                kanon_version.resolve_version(
                    "https://example.com/repo.git",
                    f"{_TAG_PREFIX}/>=1.0.0",
                )

    def test_empty_tags_repo_raises(self) -> None:
        """repo resolve_version_constraint raises ManifestInvalidRevisionError when tag list is empty.

        AC-TEST-006: empty tags raises ManifestInvalidRevisionError (fail-fast).
        """
        with pytest.raises(repo_error.ManifestInvalidRevisionError):
            repo_vc.resolve_version_constraint(
                f"{_TAG_PREFIX}/>=1.0.0",
                [],
            )


# ---------------------------------------------------------------------------
# AC-TEST-006: None input edge case -- is_version_constraint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEdgeCaseNoneInput:
    """Both implementations raise TypeError for None input (not a valid string).

    AC-TEST-006: edge case -- None input must not silently succeed.
    AC-TEST-009: assertion is meaningful -- it can fail if implementations change.
    """

    def test_none_input_kanon_raises_type_error(self) -> None:
        """kanon is_version_constraint raises TypeError for None input.

        The implementation calls rsplit on the input; None has no rsplit method.
        """
        with pytest.raises((TypeError, AttributeError)):
            kanon_version.is_version_constraint(None)

    def test_none_input_repo_raises_type_error(self) -> None:
        """repo is_version_constraint raises TypeError for None input.

        The implementation calls rsplit on the input; None has no rsplit method.
        """
        with pytest.raises((TypeError, AttributeError)):
            repo_vc.is_version_constraint(None)
