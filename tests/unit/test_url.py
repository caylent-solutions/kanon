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


@pytest.mark.unit
@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "https://github.com/org/repo.git",
            "https://github.com/org/repo",
        ),
        (
            "https://github.com/org/repo",
            "https://github.com/org/repo",
        ),
        (
            "https://github.com/org/repo/",
            "https://github.com/org/repo",
        ),
        (
            "https://github.com/org/repo.git/",
            "https://github.com/org/repo",
        ),
        (
            "https://user@github.com/org/repo",
            "https://github.com/org/repo",
        ),
        (
            "https://user@github.com/org/repo.git",
            "https://github.com/org/repo",
        ),
        (
            "https://GitHub.com/Org/Repo",
            "https://github.com/Org/Repo",
        ),
        (
            "https://h:8443/r",
            "https://h:8443/r",
        ),
        (
            "https://h:8443/r.git",
            "https://h:8443/r",
        ),
        (
            "git@github.com:org/repo.git",
            "https://github.com/org/repo",
        ),
        (
            "git@github.com:org/repo",
            "https://github.com/org/repo",
        ),
        (
            "user@github.com:org/repo.git",
            "https://github.com/org/repo",
        ),
        (
            "ssh://git@github.com/org/repo.git",
            "https://github.com/org/repo",
        ),
        (
            "ssh://github.com/org/repo.git",
            "https://github.com/org/repo",
        ),
        (
            "ssh://user@github.com/org/repo",
            "https://github.com/org/repo",
        ),
        (
            "git@GitHub.com:Org/Repo",
            "https://github.com/Org/Repo",
        ),
    ],
)
def test_canonicalize_repo_url(url: str, expected: str) -> None:
    """Each URL form must produce the expected canonical HTTPS string."""
    assert canonicalize_repo_url(url) == expected


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


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "notavalidformat",
        "just-a-hostname",
    ],
)
def test_invalid_scp_shorthand_raises(url: str) -> None:
    """A string that is not HTTPS, SSH, or valid SCP shorthand raises ValueError."""
    with pytest.raises(ValueError) as exc_info:
        canonicalize_repo_url(url)
    msg = str(exc_info.value)
    assert "ERROR:" in msg


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
