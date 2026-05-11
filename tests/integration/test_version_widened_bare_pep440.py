"""Integration tests for widened bare PEP 440 version normalisation.

Exercises resolve_version() against a real local fixture git repository
whose tag set contains all six new PEP 440 shapes introduced in
spec Section 4.0 rule 3.  Each test case asserts that the resolver
returns the matching ``refs/tags/<spec>`` for the bare version input.

No shared state: each test builds its own fixture repo via ``tmp_path``
so cases are fully isolated.

Implements AC-TEST-003 and AC-CYCLE-001 (E1-F1-S1-T1).
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
