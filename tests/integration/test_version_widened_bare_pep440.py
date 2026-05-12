"""Integration tests for widened bare PEP 440 version normalisation.

Exercises resolve_version() against a real local fixture git repository
whose tag set contains all six new PEP 440 shapes introduced in
spec Section 4.0 rule 3.  Each test case asserts that the resolver
returns the matching ``refs/tags/<spec>`` for the bare version input.

No shared state: each test builds its own fixture repo via ``tmp_path``
so cases are fully isolated.

Implements AC-TEST-003 and AC-CYCLE-001 (E1-F1-S1-T1).

Also implements AC-CYCLE-001 (E1-F1-S1-T2): the loud zero-PEP-440-parseable
error case.  A fixture repo whose tags are entirely non-PEP-440
(``release-2024``, ``snapshot-abc``, ``nightly-build``) is built;
``resolve_version`` is called with a ``==1.0.0``-style constraint; the
raised ``SystemExit`` is caught (smoke check) and the ``ValueError`` content
is verified via ``_resolve_constraint_from_tags`` directly.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from kanon_cli.version import resolve_version


def _init_fixture_repo(path: pathlib.Path, tags: list[str]) -> str:
    """Create a bare-style local git repo with the given tag names.

    Initialises a non-bare repo at ``path``, commits an empty file so
    the repo is non-empty, then creates lightweight tags for each name
    in ``tags``.  Returns the ``file://`` URL suitable for
    ``git ls-remote``.

    Args:
        path: Directory in which to initialise the git repository.
        tags: Tag names to create (e.g. ``["1.0.0a1", "2026.4.1"]``).

    Returns:
        A ``file://``-scheme URL pointing at ``path``.
    """
    path.mkdir(parents=True, exist_ok=True)

    def run(*args: str) -> None:
        subprocess.run(
            list(args),
            cwd=path,
            check=True,
            capture_output=True,
        )

    run("git", "init")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "Test User")
    (path / "README").write_text("fixture")
    run("git", "add", "README")
    run("git", "commit", "-m", "init")
    for tag in tags:
        run("git", "tag", tag)

    return f"file://{path}"


_PEP440_TAG_CASES = [
    # (spec, description)
    ("1.0.0a1", "prerelease alpha"),
    ("1.0.0+local.build", "local version"),
    ("2026.4.1", "calendar version"),
    ("1!2.0.0", "PEP 440 epoch"),
    ("1.0.0.post1", "post-release"),
    ("1.0.0.dev0", "dev-release"),
]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("spec", "description"),
    _PEP440_TAG_CASES,
    ids=[desc.replace(" ", "-") for _, desc in _PEP440_TAG_CASES],
)
def test_widened_pep440_resolve_version_returns_refs_tags(
    tmp_path: pathlib.Path,
    spec: str,
    description: str,
) -> None:
    """AC-TEST-003, AC-CYCLE-001: resolve_version returns refs/tags/<spec>.

    Builds a fixture repo with a tag named ``spec``, then asserts that
    ``resolve_version(url, spec)`` returns ``refs/tags/<spec>``.
    Each parametrized case is a separate tmp_path fixture so no shared
    state exists between cases.
    """
    all_tags = [s for s, _ in _PEP440_TAG_CASES]
    url = _init_fixture_repo(tmp_path / "repo", all_tags)

    result = resolve_version(url, spec)

    assert result == f"refs/tags/{spec}", f"Expected refs/tags/{spec!r} for {description} but got {result!r}"


@pytest.mark.integration
def test_all_non_pep440_tags_raises_loud_error(tmp_path: pathlib.Path) -> None:
    """AC-CYCLE-001 (E1-F1-S1-T2): entirely non-PEP-440 tag set triggers SystemExit.

    Smoke check: builds a fixture repo with three genuinely non-PEP-440 tags
    (``release-2024``, ``snapshot-abc``, ``nightly-build``) and calls
    ``resolve_version`` with a ``==1.0.0``-style constraint.  Asserts that
    ``SystemExit`` is raised -- resolve_version catches the inner ValueError
    and calls sys.exit(1).  Content verification is done separately in
    ``test_all_non_pep440_tags_loud_error_content``.
    """
    non_pep440_tags = ["release-2024", "snapshot-abc", "nightly-build"]
    url = _init_fixture_repo(tmp_path / "repo", non_pep440_tags)

    with pytest.raises(SystemExit):
        # resolve_version catches ValueError and calls sys.exit(1)
        resolve_version(url, "refs/tags/==1.0.0")


@pytest.mark.integration
def test_all_non_pep440_tags_loud_error_content(tmp_path: pathlib.Path) -> None:
    """AC-CYCLE-001 (E1-F1-S1-T2): loud error names all three skipped tags.

    Calls _resolve_constraint_from_tags directly (bypassing the sys.exit
    wrapper) to capture the ValueError and assert its content.
    """
    from kanon_cli.version import _resolve_constraint_from_tags

    non_pep440_tags = ["release-2024", "snapshot-abc", "nightly-build"]
    url = _init_fixture_repo(tmp_path / "repo", non_pep440_tags)

    # Build full refs as git ls-remote would return them
    result = subprocess.run(
        ["git", "ls-remote", "--tags", url],
        capture_output=True,
        text=True,
        check=True,
    )
    available_tags = [
        line.split("\t")[1]
        for line in result.stdout.strip().splitlines()
        if "\t" in line and not line.split("\t")[1].endswith("^{}")
    ]

    with pytest.raises(ValueError) as exc_info:
        _resolve_constraint_from_tags("refs/tags/==1.0.0", available_tags)

    msg = str(exc_info.value)
    assert msg.startswith("ERROR: No PEP 440-parseable version tags found under 'refs/tags'."), (
        f"Unexpected message start: {msg!r}"
    )
    assert "Skipped 3 tag(s)" in msg, f"Missing count in: {msg!r}"
    for tag_name in non_pep440_tags:
        assert f"refs/tags/{tag_name}" in msg, f"Tag {tag_name!r} not listed in error message: {msg!r}"
    assert "kanon catalog audit --check tag-format" in msg, f"Remediation pointer missing: {msg!r}"
