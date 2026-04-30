"""MS (Multi-Source) scenarios from `docs/integration-testing.md` §6.

Scenarios automated:
- MS-01: Two sources aggregate packages from both (disjoint package sets)
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import (
    kanon_clean,
    kanon_install,
    make_plain_repo,
    write_kanonenv,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_fixtures(base: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Build the fixture repos needed by MS scenarios.

    Returns:
        (pkg_alpha_bare, pkg_bravo_bare, manifest_primary_bare)

    The manifest-primary repo contains:
      - repo-specs/remote.xml
      - repo-specs/alpha-only.xml  (declares only pkg-alpha)
      - repo-specs/bravo-only.xml  (declares only pkg-bravo)
    """
    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    pkg_alpha_bare = make_plain_repo(
        content_repos,
        "pkg-alpha",
        {"README.md": "# pkg-alpha\n"},
    )
    pkg_bravo_bare = make_plain_repo(
        content_repos,
        "pkg-bravo",
        {"README.md": "# pkg-bravo\n"},
    )

    content_repos_url = content_repos.as_uri()

    remote_xml = (
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
    bravo_only_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="repo-specs/remote.xml" />\n'
        '  <project name="pkg-bravo" path=".packages/pkg-bravo"'
        ' remote="local" revision="main" />\n'
        "</manifest>\n"
    )

    manifest_primary_bare = make_plain_repo(
        manifest_repos,
        "manifest-primary",
        {
            "repo-specs/remote.xml": remote_xml,
            "repo-specs/alpha-only.xml": alpha_only_xml,
            "repo-specs/bravo-only.xml": bravo_only_xml,
        },
    )

    return pkg_alpha_bare, pkg_bravo_bare, manifest_primary_bare


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestMS:
    def test_ms_01_two_sources_aggregate_both(self, tmp_path: pathlib.Path) -> None:
        """MS-01: Two sources with disjoint manifests aggregate packages from both."""
        _, _, manifest_bare = _build_fixtures(tmp_path / "fixtures")

        work_dir = tmp_path / "test-ms01"
        work_dir.mkdir()

        manifest_url = manifest_bare.as_uri()
        write_kanonenv(
            work_dir,
            [
                ("alpha", manifest_url, "main", "repo-specs/alpha-only.xml"),
                ("bravo", manifest_url, "main", "repo-specs/bravo-only.xml"),
            ],
            marketplace_install="false",
        )

        result = kanon_install(work_dir)

        assert result.returncode == 0, (
            f"kanon install exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "kanon install: done" in result.stdout, f"'kanon install: done' not in stdout: {result.stdout!r}"

        # Both source directories must exist
        assert (work_dir / ".kanon-data" / "sources" / "alpha").is_dir(), ".kanon-data/sources/alpha/ directory missing"
        assert (work_dir / ".kanon-data" / "sources" / "bravo").is_dir(), ".kanon-data/sources/bravo/ directory missing"

        # .packages/ directory must exist and contain symlinks from both sources
        packages_dir = work_dir / ".packages"
        assert packages_dir.is_dir(), ".packages/ directory missing"

        pkg_alpha_link = packages_dir / "pkg-alpha"
        assert pkg_alpha_link.is_symlink(), ".packages/pkg-alpha is not a symlink"

        pkg_bravo_link = packages_dir / "pkg-bravo"
        assert pkg_bravo_link.is_symlink(), ".packages/pkg-bravo is not a symlink"

        # Both symlinks must resolve to valid targets
        assert pkg_alpha_link.resolve().exists(), ".packages/pkg-alpha symlink does not resolve"
        assert pkg_bravo_link.resolve().exists(), ".packages/pkg-bravo symlink does not resolve"

        kanon_clean(work_dir)
