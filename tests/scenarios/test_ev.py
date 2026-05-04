"""EV (Environment Variable Overrides) scenarios from `docs/integration-testing.md` §11.

Each scenario exercises environment-variable overrides injected via `extra_env`
on `run_kanon`, without network access.

Scenarios automated:
- EV-01: GITBASE override via environment
- EV-02: KANON_MARKETPLACE_INSTALL override via environment
- EV-03: KANON_CATALOG_SOURCE env var for bootstrap
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


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


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


def _build_custom_catalog_repo(parent: pathlib.Path) -> pathlib.Path:
    """Build a bare catalog repo with a ``catalog/my-template/`` directory and tag ``1.0.0``.

    The repo mirrors the custom-catalog fixture described in the EV-03 doc scenario:
    a git repo with a ``catalog/my-template/.kanon`` file, committed and tagged.
    """
    parent.mkdir(parents=True, exist_ok=True)
    work = parent / "custom-catalog.work"
    bare = parent / "custom-catalog.git"
    init_git_work_dir(work)

    template_dir = work / "catalog" / "my-template"
    template_dir.mkdir(parents=True)
    (template_dir / ".kanon").write_text("# Custom catalog template\nKANON_MARKETPLACE_INSTALL=false\n")
    (template_dir / "custom-readme.md").write_text("# Custom Template\n")

    run_git(["add", "catalog"], work)
    run_git(["commit", "-m", "Initial custom catalog"], work)
    run_git(["tag", "1.0.0"], work)

    run_git(["clone", "--bare", str(work), str(bare)], parent)
    return bare.resolve()


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


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

        result = kanon_install(
            work_dir,
            extra_env={"GITBASE": "https://override.example.com"},
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

        # .kanon sets KANON_MARKETPLACE_INSTALL=true; env override sets it to false
        write_kanonenv(
            work_dir,
            sources=[("primary", manifest_url, "main", "repo-specs/alpha-only.xml")],
            marketplace_install="true",
            extra_lines=[
                f"CLAUDE_MARKETPLACES_DIR={tmp_path / 'kanon-test-marketplaces'}",
            ],
        )

        result = kanon_install(
            work_dir,
            extra_env={"KANON_MARKETPLACE_INSTALL": "false"},
        )

        assert result.returncode == 0, (
            f"kanon install exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "kanon install: done" in result.stdout, f"'kanon install: done' not in stdout: {result.stdout!r}"
        # The env override disabled marketplace install, so no marketplace lifecycle
        # actions should appear in stdout.
        for marketplace_action in (
            "kanon install: preparing marketplace directory",
            "kanon install: installing marketplace plugins",
        ):
            assert marketplace_action not in result.stdout, (
                f"marketplace action {marketplace_action!r} found in stdout despite "
                f"KANON_MARKETPLACE_INSTALL=false env override: {result.stdout!r}"
            )

        kanon_clean(work_dir, extra_env={"KANON_MARKETPLACE_INSTALL": "false"})

    def test_ev_03_kanon_catalog_source_for_bootstrap(self, tmp_path: pathlib.Path) -> None:
        """EV-03: KANON_CATALOG_SOURCE env var points bootstrap list at a custom catalog repo."""
        catalog_bare = _build_custom_catalog_repo(tmp_path / "fixtures")

        # KANON_CATALOG_SOURCE format: <git_url>@<ref>
        catalog_source = f"{catalog_bare.as_uri()}@1.0.0"

        result = run_kanon(
            "bootstrap",
            "list",
            extra_env={"KANON_CATALOG_SOURCE": catalog_source},
        )

        assert result.returncode == 0, (
            f"kanon bootstrap list exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "my-template" in result.stdout, f"'my-template' not found in stdout: {result.stdout!r}"
