"""EV (Environment Variable Overrides) scenarios from `docs/integration-testing.md` §11.

Each scenario exercises environment-variable overrides injected via `extra_env`
on `run_kanon`, without network access.

Scenarios automated:
- EV-01: GITBASE override via environment
- EV-02: KANON_MARKETPLACE_INSTALL override via environment
- EV-03: KANON_CATALOG_SOURCES env var supplies the catalog source to search
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import (
    init_git_work_dir,
    kanon_clean,
    kanon_install,
    make_plain_repo,
    run_git,
    run_kanon,
    write_kanonenv,
)


def _build_manifest_fixtures(base: pathlib.Path) -> pathlib.Path:
    """Build a minimal manifest+content fixture set and return the manifest bare repo.

    The manifest repo contains:
      - repo-specs/remote.xml  -- defines a `local` remote pointing at content-repos/
      - repo-specs/alpha-only.xml -- includes remote.xml and declares pkg-alpha
    """
    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    make_plain_repo(content_repos, "pkg-alpha", {"README.md": "# pkg-alpha\n"})

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

    return make_plain_repo(
        manifest_repos,
        "manifest-primary",
        {
            "repo-specs/remote.xml": remote_xml,
            "repo-specs/alpha-only.xml": alpha_only_xml,
        },
    )


_EV03_ENTRY = "my_template"


def _build_custom_catalog_repo(parent: pathlib.Path) -> pathlib.Path:
    """Build a bare 3.0.0 catalog repo publishing one entry, tagged ``1.0.0``.

    The repo carries ``repo-specs/<entry>-marketplace.xml`` with a
    ``<catalog-metadata>`` block (the 3.0.0 catalog layout that ``kanon search``
    reads) and a ``1.0.0`` tag so the EV-03 ``@1.0.0`` catalog source resolves.
    """
    parent.mkdir(parents=True, exist_ok=True)
    work = parent / "custom-catalog.work"
    bare = parent / "custom-catalog.git"
    init_git_work_dir(work)

    repo_specs = work / "repo-specs"
    repo_specs.mkdir()
    (repo_specs / f"{_EV03_ENTRY}-marketplace.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        "  <catalog-metadata>\n"
        f"    <name>{_EV03_ENTRY}</name>\n"
        f"    <display-name>{_EV03_ENTRY} Display</display-name>\n"
        "    <description>EV-03 custom catalog entry.</description>\n"
        "    <version>==1.0.0</version>\n"
        "    <type>library</type>\n"
        "    <owner-name>EV Owner</owner-name>\n"
        "    <owner-email>ev@example.com</owner-email>\n"
        "    <keywords>ev custom</keywords>\n"
        "  </catalog-metadata>\n"
        "</manifest>\n",
        encoding="utf-8",
    )

    run_git(["add", "repo-specs"], work)
    run_git(["commit", "-m", "Initial custom catalog"], work)
    run_git(["tag", "1.0.0"], work)

    run_git(["clone", "--bare", str(work), str(bare)], parent)
    return bare.resolve()


@pytest.mark.scenario
class TestEV:
    def test_ev_01_gitbase_override_via_env(self, tmp_path: pathlib.Path) -> None:
        """EV-01: GITBASE env var overrides the value written in .kanon."""
        manifest_bare = _build_manifest_fixtures(tmp_path / "fixtures")
        manifest_url = manifest_bare.as_uri()

        work_dir = tmp_path / "test-ev01"
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[("primary", manifest_url, "main", "repo-specs/alpha-only.xml")],
            marketplace_install="false",
            extra_lines=["GITBASE=https://default.example.com"],
        )

        catalog_source = f"{manifest_url}@main"
        result = kanon_install(
            work_dir,
            extra_env={
                "GITBASE": "https://override.example.com",
                "KANON_CATALOG_SOURCE": catalog_source,
                "KANON_ALLOW_INSECURE_REMOTES": "1",
            },
        )

        assert result.returncode == 0, (
            f"kanon install exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "kanon install: done" in result.stdout, f"'kanon install: done' not in stdout: {result.stdout!r}"

        kanon_clean(work_dir)

    def test_ev_02_marketplace_install_override_via_env(self, tmp_path: pathlib.Path) -> None:
        """EV-02: KANON_MARKETPLACE_INSTALL env var overrides the file value (true -> false)."""
        manifest_bare = _build_manifest_fixtures(tmp_path / "fixtures")
        manifest_url = manifest_bare.as_uri()

        work_dir = tmp_path / "test-ev02"
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[("primary", manifest_url, "main", "repo-specs/alpha-only.xml")],
            marketplace_install="true",
            extra_lines=[
                f"CLAUDE_MARKETPLACES_DIR={tmp_path / 'kanon-test-marketplaces'}",
            ],
        )

        catalog_source = f"{manifest_url}@main"
        result = kanon_install(
            work_dir,
            extra_env={
                "KANON_MARKETPLACE_INSTALL": "false",
                "KANON_CATALOG_SOURCE": catalog_source,
                "KANON_ALLOW_INSECURE_REMOTES": "1",
            },
        )

        assert result.returncode == 0, (
            f"kanon install exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "kanon install: done" in result.stdout, f"'kanon install: done' not in stdout: {result.stdout!r}"

        for marketplace_action in (
            "kanon install: preparing marketplace directory",
            "kanon install: installing marketplace plugins",
        ):
            assert marketplace_action not in result.stdout, (
                f"marketplace action {marketplace_action!r} found in stdout despite "
                f"KANON_MARKETPLACE_INSTALL=false env override: {result.stdout!r}"
            )

        kanon_clean(work_dir, extra_env={"KANON_MARKETPLACE_INSTALL": "false"})

    def test_ev_03_kanon_catalog_sources_env_drives_search(self, tmp_path: pathlib.Path) -> None:
        """EV-03: the KANON_CATALOG_SOURCES env var supplies the catalog source to search.

        Catalog discovery moved from the removed ``bootstrap list`` to
        ``kanon search``; the ``KANON_CATALOG_SOURCES`` env var (no
        ``--catalog-source`` flag) supplies the source so the configured
        catalog's entries are listed on stdout.
        """
        catalog_bare = _build_custom_catalog_repo(tmp_path / "fixtures")

        catalog_source = f"{catalog_bare.as_uri()}@1.0.0"

        result = run_kanon(
            "search",
            extra_env={"KANON_CATALOG_SOURCES": catalog_source},
        )

        assert result.returncode == 0, (
            f"kanon search (KANON_CATALOG_SOURCES env) expected exit 0, got {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert _EV03_ENTRY in result.stdout.split(), (
            f"search must list the configured catalog's entry {_EV03_ENTRY!r}; stdout={result.stdout!r}"
        )
