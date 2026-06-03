"""Hardened parametrised coverage for ``_parse_catalog_source`` SSH ``@``-in-user-info edge cases.

Links to spec: Section 4.0 ``@`` separator parsing subsection of
``spec/kanon-list-add-lock-features-spec.md``.

Scenarios covered:

1. ssh-shorthand-with-user-info     -- ``git@host:org/repo.git@main`` splits to
                                       ``(git@host:org/repo.git, main)``
2. https-with-user-info-and-pep440  -- ``https://user@host.com/repo.git@==1.0.0`` splits to
                                       ``(https://user@host.com/repo.git, ==1.0.0)``
3. explicit-ssh-with-full-ref       -- ``ssh://git@host.com/org/repo.git@refs/tags/1.0.0`` splits to
                                       ``(ssh://git@host.com/org/repo.git, refs/tags/1.0.0)``
4. missing-ref                      -- ``git@host:org/repo.git`` raises ``ValueError``
5. empty-url                        -- ``@main`` raises ``ValueError``
6. empty-ref                        -- ``https://h/r.git@`` raises ``ValueError``
7. no-at-at-all                     -- ``https://h/r.git`` raises ``ValueError``
8. monorepo-prefixed-ref            -- ``https://h/r.git@subpackage/==1.0.0`` splits to
                                       ``(https://h/r.git, subpackage/==1.0.0)``

The end-to-end cycle (AC-CYCLE-001) verifies the ``resolve_catalog_dir`` pipeline using
plain ``file://`` fixture git repos, confirming the URL/ref produced by
``_parse_catalog_source`` flows correctly into the resolver.
"""

import pathlib
import subprocess
from collections.abc import Callable

import pytest

from kanon_cli.core.catalog import _parse_catalog_source, resolve_catalog_dir

# ---------------------------------------------------------------------------
# Parametrised unit tests -- AC-FUNC-001 through AC-FUNC-008, AC-TEST-001
# ---------------------------------------------------------------------------

_VALID_CASES = [
    (
        "git@host:org/repo.git@main",
        ("git@host:org/repo.git", "main"),
        "ssh-shorthand-with-user-info",
    ),
    (
        "https://user@host.com/repo.git@==1.0.0",
        ("https://user@host.com/repo.git", "==1.0.0"),
        "https-with-user-info-and-pep440-range",
    ),
    (
        "ssh://git@host.com/org/repo.git@refs/tags/1.0.0",
        ("ssh://git@host.com/org/repo.git", "refs/tags/1.0.0"),
        "explicit-ssh-with-full-ref",
    ),
    (
        "https://h/r.git@subpackage/==1.0.0",
        ("https://h/r.git", "subpackage/==1.0.0"),
        "monorepo-prefixed-ref",
    ),
]

_ERROR_CASES = [
    (
        "git@host:org/repo.git",
        "missing-ref",
        "git@host:org/repo.git",  # fragment of the source that must appear in the error message
    ),
    (
        "@main",
        "empty-url",
        None,  # error asserted by type only
    ),
    (
        "https://h/r.git@",
        "empty-ref",
        None,
    ),
    (
        "https://h/r.git",
        "no-at-at-all",
        None,
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize(
    "source,expected",
    [(s, e) for s, e, _ in _VALID_CASES],
    ids=[label for _, _, label in _VALID_CASES],
)
def test_parse_catalog_source_valid(source: str, expected: tuple[str, str]) -> None:
    """``_parse_catalog_source`` splits on the LAST ``@``, preserving earlier ones in user-info.

    Covers AC-FUNC-001, AC-FUNC-002, AC-FUNC-003, AC-FUNC-008.
    """
    url, ref = _parse_catalog_source(source)
    assert (url, ref) == expected, f"For source {source!r}: expected {expected!r} but got ({url!r}, {ref!r})"


@pytest.mark.unit
@pytest.mark.parametrize(
    "source,message_fragment",
    [(s, frag) for s, _, frag in _ERROR_CASES],
    ids=[label for _, label, _ in _ERROR_CASES],
)
def test_parse_catalog_source_invalid(source: str, message_fragment: str | None) -> None:
    """``_parse_catalog_source`` raises ``ValueError`` for malformed inputs.

    Covers AC-FUNC-004, AC-FUNC-005, AC-FUNC-006, AC-FUNC-007.
    """
    with pytest.raises(ValueError) as exc_info:
        _parse_catalog_source(source)

    if message_fragment is not None:
        assert message_fragment in str(exc_info.value), (
            f"Expected {message_fragment!r} to appear in error message for {source!r}; got: {exc_info.value!r}"
        )


# ---------------------------------------------------------------------------
# End-to-end cycle test -- AC-CYCLE-001
# ---------------------------------------------------------------------------


def _init_fixture_repo(base: pathlib.Path, branch: str) -> pathlib.Path:
    """Create a bare git repo under ``base/`` with a ``catalog/`` directory.

    The repo is initialised on ``branch``, contains a ``catalog/kanon/`` tree
    (mirroring the bundled catalog layout), and exposes a ``file://`` URL that
    ``git clone --depth 1 --branch <branch>`` can consume without network access.

    Returns the absolute path to the bare repo (usable as ``file://<path>``).
    """
    repo_dir = base / "fixture-repo"
    repo_dir.mkdir(parents=True)

    subprocess.run(
        ["git", "init", "-b", branch, str(repo_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    # Minimal git identity so `git commit` succeeds in CI environments that
    # have no global git config.
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
        text=True,
    )

    # Create the catalog structure expected by `_clone_remote_catalog`.
    catalog_kanon = repo_dir / "catalog" / "kanon"
    catalog_kanon.mkdir(parents=True)
    (catalog_kanon / "README.md").write_text("fixture\n")

    subprocess.run(
        ["git", "-C", str(repo_dir), "add", "."],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_dir), "commit", "-m", "init"],
        check=True,
        capture_output=True,
        text=True,
    )

    return repo_dir


@pytest.mark.unit
@pytest.mark.parametrize(
    "build_source,branch",
    [
        # Case 1: Plain file:// URL with a branch name ref.
        (
            lambda repo_url: f"{repo_url}@main",
            "main",
        ),
        # Case 2: Plain file:// URL with a different branch name ref.
        (
            lambda repo_url: f"{repo_url}@feature",
            "feature",
        ),
        # Case 3: Plain file:// URL with a tag ref.
        (
            lambda repo_url: f"{repo_url}@v1.0.0",
            "v1.0.0",
        ),
    ],
    ids=[
        "plain-file-url-branch-main",
        "plain-file-url-branch-feature",
        "plain-file-url-tag-ref",
    ],
)
def test_round_trip_through_catalog_resolver(
    tmp_path: pathlib.Path,
    build_source: Callable[[str], str],
    branch: str,
) -> None:
    """The URL/ref produced by ``_parse_catalog_source`` flows correctly through the resolver.

    Covers AC-CYCLE-001: builds a ``file://`` fixture git repo, constructs the
    ``<git-url>@<ref>`` string, calls ``resolve_catalog_dir``, and asserts the
    resolver returns a path under the expected clone directory that contains the
    ``catalog/`` subtree.

    Each parametrised case uses a plain ``file://`` URL pointing at the fixture
    repo and verifies that the resolver clones the repo at the correct ref,
    returning a path containing the expected ``catalog/`` subtree.
    """
    fixture_base = tmp_path / "fixture"
    fixture_base.mkdir()

    repo_dir = _init_fixture_repo(fixture_base, "main")

    # For the tag case, create the tag on the fixture repo.
    if branch != "main" and branch != "feature":
        subprocess.run(
            ["git", "-C", str(repo_dir), "tag", branch],
            check=True,
            capture_output=True,
            text=True,
        )
    elif branch == "feature":
        # Create the feature branch in the fixture repo.
        subprocess.run(
            ["git", "-C", str(repo_dir), "checkout", "-b", branch],
            check=True,
            capture_output=True,
            text=True,
        )
        # Return to main so the fixture repo HEAD is on main (the default clone branch).
        subprocess.run(
            ["git", "-C", str(repo_dir), "checkout", "main"],
            check=True,
            capture_output=True,
            text=True,
        )

    file_url = f"file://{repo_dir}"
    source = build_source(file_url)

    # Verify the splitter produces the right (url, ref) for this source string.
    url, ref = _parse_catalog_source(source)
    assert url == file_url, f"Splitter produced wrong URL for {source!r}: got {url!r}"
    assert ref == branch, f"Splitter produced wrong ref for {source!r}: got {ref!r}"

    # Now run through the full public entry point -- resolve_catalog_dir.
    result = resolve_catalog_dir(source)

    # The resolver returns the catalog/ directory inside the cloned repo.
    assert result.is_dir(), f"resolve_catalog_dir returned a non-directory path: {result}"
    assert result.name == "catalog", f"resolve_catalog_dir should return the catalog/ subdirectory; got: {result}"
    assert (result / "kanon").is_dir(), f"Expected catalog/kanon/ to exist in cloned repo; result path: {result}"
