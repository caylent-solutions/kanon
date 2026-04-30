"""CD (Collision Detection) scenarios from `docs/integration-testing.md` §7.

Scenarios automated:
- CD-01: Two sources producing the same package name -- exit 1, collision error
- CD-02: Three sources, collision between two -- exit 1, alphabetical processing order
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import (
    kanon_install,
    make_plain_repo,
    write_kanonenv,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_fixtures(
    base: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Build manifest fixture repos needed by CD scenarios.

    Returns:
        (manifest_primary_bare, manifest_collision_bare)

    manifest-primary contains:
      - repo-specs/remote.xml
      - repo-specs/alpha-only.xml  (path=.packages/pkg-alpha)
      - repo-specs/packages.xml    (both pkg-alpha and pkg-bravo)

    manifest-collision contains:
      - repo-specs/remote.xml
      - repo-specs/collision.xml   (pkg-collider mapped to path=.packages/pkg-alpha)
    """
    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    make_plain_repo(content_repos, "pkg-alpha", {"README.md": "# pkg-alpha\n"})
    make_plain_repo(content_repos, "pkg-bravo", {"README.md": "# pkg-bravo\n"})
    make_plain_repo(content_repos, "pkg-collider", {"README.md": "# pkg-collider\n"})

    content_repos_url = content_repos.as_uri()

    primary_remote_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_repos_url}/" />\n'
        '  <default remote="local" revision="main" sync-j="4" />\n'
        "</manifest>\n"
    )
    alpha_only_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="repo-specs/remote.xml" />\n'
        '  <project name="pkg-alpha" path=".packages/pkg-alpha"'
        ' remote="local" revision="main" />\n'
        "</manifest>\n"
    )
    packages_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="repo-specs/remote.xml" />\n'
        '  <project name="pkg-alpha" path=".packages/pkg-alpha"'
        ' remote="local" revision="main" />\n'
        '  <project name="pkg-bravo" path=".packages/pkg-bravo"'
        ' remote="local" revision="main" />\n'
        "</manifest>\n"
    )

    manifest_primary_bare = make_plain_repo(
        manifest_repos,
        "manifest-primary",
        {
            "repo-specs/remote.xml": primary_remote_xml,
            "repo-specs/alpha-only.xml": alpha_only_xml,
            "repo-specs/packages.xml": packages_xml,
        },
    )

    collision_remote_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_repos_url}/" />\n'
        '  <default remote="local" revision="main" sync-j="4" />\n'
        "</manifest>\n"
    )
    # pkg-collider mapped to .packages/pkg-alpha -- same path as pkg-alpha above
    collision_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="repo-specs/remote.xml" />\n'
        '  <project name="pkg-collider" path=".packages/pkg-alpha"'
        ' remote="local" revision="main" />\n'
        "</manifest>\n"
    )

    manifest_collision_bare = make_plain_repo(
        manifest_repos,
        "manifest-collision",
        {
            "repo-specs/remote.xml": collision_remote_xml,
            "repo-specs/collision.xml": collision_xml,
        },
    )

    return manifest_primary_bare, manifest_collision_bare


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestCD:
    def test_cd_01_two_sources_collision(self, tmp_path: pathlib.Path) -> None:
        """CD-01: Two sources producing the same package path exits 1 with collision error."""
        manifest_primary_bare, manifest_collision_bare = _build_fixtures(tmp_path / "fixtures")

        work_dir = tmp_path / "test-cd01"
        work_dir.mkdir()

        primary_url = manifest_primary_bare.as_uri()
        collision_url = manifest_collision_bare.as_uri()

        write_kanonenv(
            work_dir,
            [
                ("primary", primary_url, "main", "repo-specs/alpha-only.xml"),
                ("secondary", collision_url, "main", "repo-specs/collision.xml"),
            ],
            marketplace_install="false",
        )

        result = kanon_install(work_dir)

        assert result.returncode == 1, (
            f"kanon install should exit 1 on collision, got {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Package collision" in result.stderr, f"'Package collision' not in stderr: {result.stderr!r}"
        assert "pkg-alpha" in result.stderr, f"'pkg-alpha' not in stderr: {result.stderr!r}"

    def test_cd_02_three_sources_collision_between_two(self, tmp_path: pathlib.Path) -> None:
        """CD-02: Three sources where two collide; alphabetical processing means aaa vs bbb collide."""
        manifest_primary_bare, manifest_collision_bare = _build_fixtures(tmp_path / "fixtures")

        work_dir = tmp_path / "test-cd02"
        work_dir.mkdir()

        primary_url = manifest_primary_bare.as_uri()
        collision_url = manifest_collision_bare.as_uri()

        # Sources are named so alphabetical order is: aaa, bbb, ccc
        # aaa provides pkg-alpha; bbb also maps pkg-collider to .packages/pkg-alpha --> collision
        write_kanonenv(
            work_dir,
            [
                ("aaa", primary_url, "main", "repo-specs/alpha-only.xml"),
                ("bbb", collision_url, "main", "repo-specs/collision.xml"),
                ("ccc", primary_url, "main", "repo-specs/packages.xml"),
            ],
            marketplace_install="false",
        )

        result = kanon_install(work_dir)

        assert result.returncode == 1, (
            f"kanon install should exit 1 on collision, got {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Package collision" in result.stderr, f"'Package collision' not in stderr: {result.stderr!r}"
        assert "pkg-alpha" in result.stderr, f"'pkg-alpha' not in stderr: {result.stderr!r}"
