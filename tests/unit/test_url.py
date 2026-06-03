"""Unit tests for kanon_cli.core.url canonicalization.

Covers every canonicalisation rule from spec Section 4.0:
  1. Scheme detection (https, ssh, SCP-shorthand).
  2. Host lowercasing.
  3. User-info stripping.
  4. Trailing slash strip.
  5. Trailing .git suffix strip.
  6. Scheme normalisation to https.
  7. Query-string / fragment rejection.
  8. Empty / whitespace-only input rejection.
  9. Port preservation.
"""

import pytest

from kanon_cli.core.url import canonicalize_repo_url


# ---------------------------------------------------------------------------
# AC-FUNC-001 to AC-FUNC-007 -- canonical-form tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "url, expected",
    [
        # AC-FUNC-001: HTTPS with .git suffix stripped
        (
            "https://github.com/org/repo.git",
            "https://github.com/org/repo",
        ),
        # HTTPS without .git -- unchanged
        (
            "https://github.com/org/repo",
            "https://github.com/org/repo",
        ),
        # AC-FUNC-004: trailing slash stripped
        (
            "https://github.com/org/repo/",
            "https://github.com/org/repo",
        ),
        # AC-FUNC-004: trailing .git AND trailing slash -- both stripped
        (
            "https://github.com/org/repo.git/",
            "https://github.com/org/repo",
        ),
        # AC-FUNC-005: embedded user-info in HTTPS URL stripped
        (
            "https://user@github.com/org/repo",
            "https://github.com/org/repo",
        ),
        # AC-FUNC-005: embedded user-info in HTTPS URL with .git suffix
        (
            "https://user@github.com/org/repo.git",
            "https://github.com/org/repo",
        ),
        # AC-FUNC-006: host lowercased, path case preserved
        (
            "https://GitHub.com/Org/Repo",
            "https://github.com/Org/Repo",
        ),
        # AC-FUNC-007: port preserved
        (
            "https://h:8443/r",
            "https://h:8443/r",
        ),
        # Port with .git suffix
        (
            "https://h:8443/r.git",
            "https://h:8443/r",
        ),
        # AC-FUNC-002: SCP shorthand canonicalises to HTTPS
        (
            "git@github.com:org/repo.git",
            "https://github.com/org/repo",
        ),
        # SCP shorthand without .git suffix
        (
            "git@github.com:org/repo",
            "https://github.com/org/repo",
        ),
        # AC-FUNC-005: SCP shorthand with user stripped (user@host:path)
        (
            "user@github.com:org/repo.git",
            "https://github.com/org/repo",
        ),
        # AC-FUNC-003: explicit ssh:// scheme
        (
            "ssh://git@github.com/org/repo.git",
            "https://github.com/org/repo",
        ),
        # ssh:// without user-info
        (
            "ssh://github.com/org/repo.git",
            "https://github.com/org/repo",
        ),
        # AC-FUNC-005: ssh:// with user-info stripped
        (
            "ssh://user@github.com/org/repo",
            "https://github.com/org/repo",
        ),
        # AC-FUNC-006: host lowercase in SCP form
        (
            "git@GitHub.com:Org/Repo",
            "https://github.com/Org/Repo",
        ),
    ],
)
def test_canonicalize_repo_url(url: str, expected: str) -> None:
    """Each URL form must produce the expected canonical HTTPS string."""
    assert canonicalize_repo_url(url) == expected


# ---------------------------------------------------------------------------
# AC-FUNC-008 -- query-string rejection
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "https://h/r?branch=main",
        "https://github.com/org/repo.git?ref=v1",
    ],
)
def test_query_string_raises(url: str) -> None:
    """Inputs with a query string raise ValueError naming the offending URL."""
    with pytest.raises(ValueError) as exc_info:
        canonicalize_repo_url(url)
    msg = str(exc_info.value)
    assert msg.startswith("ERROR:")
    assert url in msg


# ---------------------------------------------------------------------------
# AC-FUNC-009 -- fragment rejection
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "https://h/r#L42",
        "https://github.com/org/repo.git#readme",
    ],
)
def test_fragment_raises(url: str) -> None:
    """Inputs with a fragment raise ValueError naming the offending URL."""
    with pytest.raises(ValueError) as exc_info:
        canonicalize_repo_url(url)
    msg = str(exc_info.value)
    assert msg.startswith("ERROR:")
    assert url in msg


# ---------------------------------------------------------------------------
# AC-FUNC-010 -- empty / whitespace-only input
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "\t\n",
    ],
)
def test_empty_or_whitespace_raises(url: str) -> None:
    """Empty or whitespace-only input raises ValueError."""
    with pytest.raises(ValueError) as exc_info:
        canonicalize_repo_url(url)
    msg = str(exc_info.value)
    assert "ERROR:" in msg


# ---------------------------------------------------------------------------
# Invalid SCP shorthand -- exercises _parse_scp error path
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        # No colon and no recognised scheme -- fails SCP regex.
        "notavalidformat",
        # Path-less colon-less string.
        "just-a-hostname",
    ],
)
def test_invalid_scp_shorthand_raises(url: str) -> None:
    """A string that is not HTTPS, SSH, or valid SCP shorthand raises ValueError."""
    with pytest.raises(ValueError) as exc_info:
        canonicalize_repo_url(url)
    msg = str(exc_info.value)
    assert "ERROR:" in msg


# ---------------------------------------------------------------------------
# AC-CYCLE-001 / AC-TEST-002 -- equivalence-set test
# Six real-world spellings must all canonicalise to the same string.
# ---------------------------------------------------------------------------

_EQUIVALENCE_SET = [
    "https://github.com/caylent-solutions/kanon",
    "https://github.com/caylent-solutions/kanon.git",
    "https://github.com/caylent-solutions/kanon.git/",
    "git@github.com:caylent-solutions/kanon.git",
    "ssh://git@github.com/caylent-solutions/kanon.git",
    "https://user@github.com/caylent-solutions/kanon.git",
]

_EXPECTED_CANONICAL = "https://github.com/caylent-solutions/kanon"


@pytest.mark.unit
def test_equivalence_set_all_produce_same_canonical() -> None:
    """All six spellings of a single repo URL produce one canonical string."""
    results = {canonicalize_repo_url(u) for u in _EQUIVALENCE_SET}
    assert len(results) == 1, f"Expected 1 canonical form, got {results}"
    assert _EXPECTED_CANONICAL in results


@pytest.mark.unit
@pytest.mark.parametrize("url", _EQUIVALENCE_SET)
def test_equivalence_set_each_spelling(url: str) -> None:
    """Each individual spelling canonicalises to the expected HTTPS form."""
    assert canonicalize_repo_url(url) == _EXPECTED_CANONICAL
