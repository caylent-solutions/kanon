"""LF (Linkfile) scenarios from `docs/integration-testing.md` §8.

Scenarios automated:
- LF-01: Package with linkfile elements creates symlinks inside the source directory
"""

from __future__ import annotations

import os
import pathlib

import pytest

from tests.scenarios.conftest import (
    kanon_clean,
    kanon_install,
    make_plain_repo,
    project_address_for,
    write_kanonenv,
)


def _build_fixtures(base: pathlib.Path) -> pathlib.Path:
    """Build fixture repos needed by LF scenarios.

    Returns:
        manifest_linkfile_bare

    The pkg-linked content repo contains:
      - config/app-config.json
      - config/lint.toml

    The manifest-linkfile repo contains:
      - repo-specs/remote.xml
      - repo-specs/linkfile.xml  (project with two <linkfile> elements)
    """
    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    make_plain_repo(
        content_repos,
        "pkg-linked",
        {
            "config/app-config.json": '{"setting": "value"}\n',
            "config/lint.toml": "lint_rule = true\n",
            "README.md": "# Linked Package\n",
        },
    )

    content_repos_url = content_repos.as_uri()

    remote_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_repos_url}/" />\n'
        '  <default remote="local" revision="main" sync-j="4" />\n'
        "</manifest>\n"
    )

    linkfile_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="repo-specs/remote.xml" />\n'
        '  <project name="pkg-linked" path=".packages/pkg-linked"'
        ' remote="local" revision="main">\n'
        '    <linkfile src="config/app-config.json" dest="app-config.json" />\n'
        '    <linkfile src="config/lint.toml" dest="lint.toml" />\n'
        "  </project>\n"
        "</manifest>\n"
    )

    manifest_linkfile_bare = make_plain_repo(
        manifest_repos,
        "manifest-linkfile",
        {
            "repo-specs/remote.xml": remote_xml,
            "repo-specs/linkfile.xml": linkfile_xml,
        },
    )

    return manifest_linkfile_bare


@pytest.mark.scenario
class TestLF:
    def test_lf_01_linkfile_elements_create_symlinks(self, tmp_path: pathlib.Path) -> None:
        """LF-01: Package with linkfile elements creates symlinks in the source directory."""
        manifest_linkfile_bare = _build_fixtures(tmp_path / "fixtures")

        work_dir = tmp_path / "test-lf01"
        work_dir.mkdir()

        manifest_url = manifest_linkfile_bare.as_uri()
        write_kanonenv(
            work_dir,
            [("linked", manifest_url, "main", "repo-specs/linkfile.xml")],
            marketplace_install="false",
        )

        catalog_source = f"{manifest_url}@main"
        result = kanon_install(
            work_dir,
            extra_env={"KANON_CATALOG_SOURCE": catalog_source, "KANON_ALLOW_INSECURE_REMOTES": "1"},
        )

        assert result.returncode == 0, (
            f"kanon install exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "kanon install: done" in result.stdout, f"'kanon install: done' not in stdout: {result.stdout!r}"

        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"

        pkg_linked_link = store_base / ".packages" / "pkg-linked"
        assert pkg_linked_link.is_symlink(), ".packages/pkg-linked is not a symlink"

        project_address = project_address_for(work_dir)
        sources_linked = store_base / ".kanon-data" / "sources" / project_address / "linked"
        assert sources_linked.is_dir(), ".kanon-data/sources/<project_address>/linked/ directory missing"

        app_config_link = sources_linked / "app-config.json"
        assert app_config_link.is_symlink(), (
            ".kanon-data/sources/<project_address>/linked/app-config.json is not a symlink"
        )
        assert app_config_link.resolve().exists(), (
            ".kanon-data/sources/<project_address>/linked/app-config.json symlink does not resolve to a valid file"
        )

        lint_toml_link = sources_linked / "lint.toml"
        assert lint_toml_link.is_symlink(), ".kanon-data/sources/<project_address>/linked/lint.toml is not a symlink"
        assert lint_toml_link.resolve().exists(), (
            ".kanon-data/sources/<project_address>/linked/lint.toml symlink does not resolve to a valid file"
        )

        kanon_clean(work_dir)


@pytest.mark.scenario
class TestLF02CopyfileAbsoluteDest:
    """LF-02: `<copyfile>` delivers a real file into the consuming project.

    `<copyfile>` writes bytes where `<linkfile>` creates a symlink, which is how a
    manifest delivers content that cannot be a symlink -- a CI workflow, for
    instance. Every existing copyfile test constructs `_CopyFile` directly and
    calls the private `._Copy()`; none drives an absolute dest through a real
    `kanon install`, so the feature the documentation advertises had no end-to-end
    coverage.
    """

    def test_absolute_copyfile_dest_delivers_a_real_file(
        self, tmp_path: pathlib.Path, scenario_workspace: pathlib.Path
    ) -> None:
        content_repos = tmp_path / "content-repos"
        manifest_repos = tmp_path / "manifest-repos"
        content_repos.mkdir(parents=True)
        manifest_repos.mkdir(parents=True)

        make_plain_repo(content_repos, "ci-config", {"workflows/ci.yml": "name: ci\n"})

        project = scenario_workspace / "consumer"
        project.mkdir(parents=True)
        delivered = project / ".github" / "workflows" / "ci.yml"

        manifest = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{content_repos.as_uri()}/" />\n'
            '  <default remote="local" revision="main" />\n'
            '  <project name="ci-config" path=".packages/ci-config" remote="local" revision="main">\n'
            f'    <copyfile src="workflows/ci.yml" dest="{delivered}" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_bare = make_plain_repo(manifest_repos, "manifest", {"repo-specs/ci.xml": manifest})

        write_kanonenv(project, [("ci", f"file://{manifest_bare}", "main", "repo-specs/ci.xml")])

        result = kanon_install(project, extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"})
        assert result.returncode == 0, f"install failed: {result.stderr!r}"

        assert delivered.is_file(), f"expected a delivered file at {delivered}"
        assert not delivered.is_symlink(), "copyfile must deliver a real file, not a symlink"
        assert delivered.read_text(encoding="utf-8") == "name: ci\n"

    def test_absolute_copyfile_dest_outside_the_project_is_refused(
        self, tmp_path: pathlib.Path, scenario_workspace: pathlib.Path
    ) -> None:
        """The boundary holds through a real install, not only in unit tests."""
        content_repos = tmp_path / "content-repos"
        manifest_repos = tmp_path / "manifest-repos"
        content_repos.mkdir(parents=True)
        manifest_repos.mkdir(parents=True)

        make_plain_repo(content_repos, "ci-config", {"workflows/ci.yml": "name: ci\n"})

        project = scenario_workspace / "consumer-refused"
        project.mkdir(parents=True)
        outside = tmp_path / "outside" / "stolen.yml"

        manifest = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{content_repos.as_uri()}/" />\n'
            '  <default remote="local" revision="main" />\n'
            '  <project name="ci-config" path=".packages/ci-config" remote="local" revision="main">\n'
            f'    <copyfile src="workflows/ci.yml" dest="{outside}" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_bare = make_plain_repo(manifest_repos, "manifest", {"repo-specs/ci.xml": manifest})

        write_kanonenv(project, [("ci", f"file://{manifest_bare}", "main", "repo-specs/ci.xml")])

        result = kanon_install(project, extra_env={"KANON_ALLOW_INSECURE_REMOTES": "1"})

        assert result.returncode != 0, "an install writing outside every permitted root must fail"
        assert not outside.exists(), f"nothing must be written to {outside}"
        assert "permitted root" in result.stderr, f"the failure must name the boundary; got {result.stderr!r}"
