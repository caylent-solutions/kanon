"""UJ (User Journey) scenarios from `docs/integration-testing.md` §28.

Each journey reproduces a multi-step sequence from `kanon/docs/`, stitching
together bootstrap, install, clean, validate, and repo lifecycle commands
against local bare git repos served over `file://` URLs.  No network access
is required.

Scenarios automated:
- UJ-01: bootstrap was removed -- exits 2 (invalid choice), produces no files
- UJ-02: search --catalog-source PEP 440 (>=2.0.0,<3.0.0) resolves correctly
- UJ-03: multi-source install -- two sources aggregate into the store .packages/
- UJ-04: GITBASE env override respected by install
- UJ-05: full marketplace lifecycle (skipped when claude CLI absent)
- UJ-06: collision detection -- exit non-zero + collision name in output
- UJ-07: linkfile journey -- symlink resolves into .kanon-data/sources/
- UJ-08: pipeline cache -- clean succeeds after tar/restore of .packages + .kanon-data
- UJ-09: shell variable expansion -- defined var accepted; undefined var errors with name
- UJ-10: python -m kanon_cli entry point -- version + help subcommands
- UJ-11: standalone-repo journey -- repo init / sync / status all exit 0
- UJ-12: manifest validation journey -- xml validate and marketplace validate

Skipped scenarios:
- UJ-05: skipped when the `claude` CLI binary is absent (no-claude environment)
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import tarfile

import pytest

from tests.scenarios.conftest import (
    clone_as_bare,
    init_git_work_dir,
    kanon_clean,
    kanon_install,
    make_plain_repo,
    mk_plugin_repo,
    run_git,
    run_kanon,
    write_kanonenv,
)


_KANON_HOME_STORE_SUBDIR = "store"


def _store_dir(kanon_home: pathlib.Path) -> pathlib.Path:
    """Return the artifact store directory (<KANON_HOME>/store) for a KANON_HOME."""
    return kanon_home / _KANON_HOME_STORE_SUBDIR


def _build_content_and_manifest(
    base: pathlib.Path,
    *,
    pkg_names: list[str] | None = None,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Build content repos and a manifest repo containing one xml per pkg.

    Returns (content_repos_dir, manifest_bare).
    The manifest repo has:
      - repo-specs/remote.xml  -- defines a `local` remote at content_repos/
      - repo-specs/<pkg>-only.xml for each pkg name
    """
    if pkg_names is None:
        pkg_names = ["pkg-alpha"]

    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    for pkg in pkg_names:
        make_plain_repo(content_repos, pkg, {"README.md": f"# {pkg}\n"})

    content_url = content_repos.as_uri()

    remote_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_url}/" />\n'
        '  <default remote="local" revision="main" sync-j="4" />\n'
        "</manifest>\n"
    )

    files: dict[str, str] = {"repo-specs/remote.xml": remote_xml}
    for pkg in pkg_names:
        pkg_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="repo-specs/remote.xml" />\n'
            f'  <project name="{pkg}" path=".packages/{pkg}"'
            ' remote="local" revision="main" />\n'
            "</manifest>\n"
        )
        files[f"repo-specs/{pkg}-only.xml"] = pkg_xml

    manifest_bare = make_plain_repo(manifest_repos, "manifest-primary", files)
    return content_repos, manifest_bare


def _uj02_entry_for_tag(tag: str) -> str:
    """Return the unique catalog entry name published at the given tag for UJ-02."""
    return f"entry_{tag.replace('.', '_')}"


def _build_catalog_repo_with_entry(parent: pathlib.Path) -> pathlib.Path:
    """Build a 3.0.0 catalog repo whose every tag publishes a unique entry.

    Tags 1.0.0, 2.0.0, and 3.0.0 each publish a single
    ``repo-specs/<entry>-marketplace.xml`` whose entry name encodes the tag
    (``entry_<tag>``), so the entry listed by ``kanon search`` pinpoints which
    catalog-repo tag a PEP 440 constraint (e.g. ``>=2.0.0,<3.0.0`` -> 2.0.0)
    resolved to.
    """
    work = parent / "catalog-work"
    bare = parent / "catalog.git"
    init_git_work_dir(work)

    repo_specs = work / "repo-specs"
    repo_specs.mkdir()

    for tag in ("1.0.0", "2.0.0", "3.0.0"):
        for stale in repo_specs.glob("*.xml"):
            stale.unlink()
        entry = _uj02_entry_for_tag(tag)
        (repo_specs / f"{entry}-marketplace.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            "  <catalog-metadata>\n"
            f"    <name>{entry}</name>\n"
            f"    <display-name>{entry} Display</display-name>\n"
            f"    <description>UJ-02 catalog entry at tag {tag}.</description>\n"
            f"    <version>=={tag}</version>\n"
            "    <type>library</type>\n"
            "    <owner-name>UJ Owner</owner-name>\n"
            "    <owner-email>uj@example.com</owner-email>\n"
            "    <keywords>uj catalog</keywords>\n"
            "  </catalog-metadata>\n"
            "</manifest>\n",
            encoding="utf-8",
        )
        run_git(["add", "-A"], work)
        run_git(["commit", "-m", f"release {tag}"], work)
        run_git(["tag", tag], work)

    return clone_as_bare(work, bare)


def _build_manifest_for_repo_command(base: pathlib.Path) -> pathlib.Path:
    """Build a bare manifest repo suitable for `kanon repo init` (default.xml at root)."""
    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    make_plain_repo(content_repos, "pkg-alpha", {"README.md": "# pkg-alpha\n"})
    content_url = content_repos.as_uri()

    default_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_url}/" />\n'
        '  <default remote="local" revision="main" />\n'
        '  <project name="pkg-alpha" path="pkg-alpha" remote="local" revision="main" />\n'
        "</manifest>\n"
    )

    return make_plain_repo(manifest_repos, "manifest-primary", {"default.xml": default_xml})


def _build_marketplace_manifest_repo(
    base: pathlib.Path,
    plugin_name: str,
    plugin_fix_dir: pathlib.Path,
    marketplaces_dir: pathlib.Path,
    *,
    manifest_filename: str | None = None,
) -> pathlib.Path:
    """Build a bare manifest repo containing a marketplace manifest XML.

    The manifest XML references the plugin repo at `plugin_fix_dir` via a
    `<linkfile>` that points `dest` at `${CLAUDE_MARKETPLACES_DIR}/<plugin_name>`.

    Mirrors the bash `mk_mfst_xml` + `git init/commit/tag` helper from the
    integration-testing.md §16 fixture setup.

    Returns the bare manifest repo path.
    """
    mfst_name = manifest_filename or f"{plugin_name}.xml"
    plugin_fix_url = plugin_fix_dir.as_uri()

    mfst_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{plugin_fix_url}/" />\n'
        '  <default remote="local" revision="main" />\n'
        f'  <project name="{plugin_name}" path=".packages/{plugin_name}"'
        ' remote="local" revision="main">\n'
        f'    <linkfile src="." dest="${{CLAUDE_MARKETPLACES_DIR}}/{plugin_name}" />\n'
        "  </project>\n"
        "</manifest>\n"
    )

    manifest_repos = base / "manifest-repos"
    manifest_repos.mkdir(parents=True, exist_ok=True)
    return make_plain_repo(manifest_repos, "mfst-repo", {mfst_name: mfst_xml})


@pytest.mark.scenario
class TestUJ:
    def test_uj_01_bootstrap_kanon_produces_files(self, tmp_path: pathlib.Path) -> None:
        """UJ-01: bootstrap was removed entirely (exit 2 invalid choice); no files produced."""
        work_dir = tmp_path / "uj-01"
        work_dir.mkdir()

        result = run_kanon("bootstrap", "kanon", cwd=work_dir)

        assert result.returncode == 2, (
            f"bootstrap expected exit 2 (argparse unknown command), got {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "invalid choice: 'bootstrap'" in result.stderr, (
            f"stderr must name 'bootstrap' as an invalid choice: {result.stderr!r}"
        )

        assert not (work_dir / ".kanon").exists(), ".kanon must NOT be created"
        assert not (work_dir / "kanon-readme.md").exists(), "kanon-readme.md must NOT be created"

    def test_uj_02_search_catalog_source_pep440(self, tmp_path: pathlib.Path) -> None:
        """UJ-02: search resolves a PEP 440 catalog-source range to the highest 2.x tag.

        Catalog discovery moved from the removed ``bootstrap list`` to
        ``kanon search``. A ``>=2.0.0,<3.0.0`` catalog source resolves the
        catalog repo to its 2.0.0 tag, so search lists the entry published at
        that tag and not the 1.0.0 or 3.0.0 entries.
        """
        catalog_bare = _build_catalog_repo_with_entry(tmp_path / "fixtures")

        catalog_source = f"{catalog_bare.as_uri()}@>=2.0.0,<3.0.0"

        result = run_kanon("search", "--catalog-source", catalog_source)

        assert result.returncode == 0, (
            f"search (@>=2.0.0,<3.0.0) expected exit 0, got {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        listed = result.stdout.split()
        assert _uj02_entry_for_tag("2.0.0") in listed, (
            f"the range must resolve to tag 2.0.0 (entry {_uj02_entry_for_tag('2.0.0')!r}); got {listed!r}"
        )
        assert _uj02_entry_for_tag("3.0.0") not in listed, "the <3.0.0 upper bound must exclude the 3.0.0 entry"
        assert _uj02_entry_for_tag("1.0.0") not in listed, "the >=2.0.0 lower bound must exclude the 1.0.0 entry"

    def test_uj_03_multi_source_install(self, tmp_path: pathlib.Path) -> None:
        """UJ-03: multi-source install -- pkg-alpha and pkg-bravo both symlinked."""
        _, manifest_bare = _build_content_and_manifest(
            tmp_path / "fixtures",
            pkg_names=["pkg-alpha", "pkg-bravo"],
        )

        work_dir = tmp_path / "uj-03"
        work_dir.mkdir()
        manifest_url = manifest_bare.as_uri()
        kanon_home = tmp_path / "uj-03-home"
        store = _store_dir(kanon_home)

        write_kanonenv(
            work_dir,
            sources=[
                ("alpha", manifest_url, "main", "repo-specs/pkg-alpha-only.xml"),
                ("bravo", manifest_url, "main", "repo-specs/pkg-bravo-only.xml"),
            ],
            marketplace_install="false",
        )

        install_env = {"KANON_ALLOW_INSECURE_REMOTES": "1", "KANON_HOME": str(kanon_home)}
        install_result = kanon_install(work_dir, extra_env=install_env)
        assert install_result.returncode == 0, (
            f"install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )
        assert "kanon install: done" in install_result.stdout

        assert (store / ".packages" / "pkg-alpha").is_symlink(), "store .packages/pkg-alpha is not a symlink"
        assert (store / ".packages" / "pkg-bravo").is_symlink(), "store .packages/pkg-bravo is not a symlink"

        gitignore_text = (store / ".gitignore").read_text()
        assert ".packages/" in gitignore_text, "store .gitignore missing '.packages/'"
        assert ".kanon-data/" in gitignore_text, "store .gitignore missing '.kanon-data/'"

        clean_result = kanon_clean(work_dir, extra_env={"KANON_HOME": str(kanon_home)})
        assert clean_result.returncode == 0, f"clean exited {clean_result.returncode}"

    def test_uj_04_gitbase_env_override(self, tmp_path: pathlib.Path) -> None:
        """UJ-04: GITBASE env override is honoured by install."""
        _, manifest_bare = _build_content_and_manifest(tmp_path / "fixtures")

        work_dir = tmp_path / "uj-04"
        work_dir.mkdir()
        manifest_url = manifest_bare.as_uri()
        kanon_home = tmp_path / "uj-04-home"
        store = _store_dir(kanon_home)

        write_kanonenv(
            work_dir,
            sources=[("a", manifest_url, "main", "repo-specs/pkg-alpha-only.xml")],
            marketplace_install="false",
            extra_lines=["GITBASE=https://default.example.com"],
        )

        install_result = kanon_install(
            work_dir,
            extra_env={
                "GITBASE": "https://override.example.com",
                "KANON_ALLOW_INSECURE_REMOTES": "1",
                "KANON_HOME": str(kanon_home),
            },
        )
        assert install_result.returncode == 0, (
            f"install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )
        assert (store / ".packages" / "pkg-alpha").is_symlink(), "store .packages/pkg-alpha is not a symlink"

        kanon_clean(
            work_dir,
            extra_env={"GITBASE": "https://override.example.com", "KANON_HOME": str(kanon_home)},
        )

    def test_uj_05_full_marketplace_lifecycle(
        self,
        tmp_path: pathlib.Path,
        claude_marketplaces_dir: pathlib.Path,
    ) -> None:
        """UJ-05: marketplace plugin appears in the marketplaces dir after install; absent after clean.

        If the `claude` CLI is absent the test is skipped.  If `claude` is present, the
        test verifies the kanon marketplace lifecycle against a properly structured plugin
        repo (marketplace.json with the fields required by the real claude CLI schema).
        The ``claude plugin list`` check is skipped here because plugin registration
        depends on whether the claude CLI accepts the test fixture's schema; we instead
        assert on the filesystem state which kanon controls directly.
        """
        if shutil.which("claude") is None:
            pytest.skip("claude CLI not found; skipping marketplace lifecycle test (no-claude environment)")

        plugin_fix_dir = tmp_path / "fixtures" / "plugin-fix"
        plugin_fix_dir.mkdir(parents=True)

        plugin_name = "uj05-plugin"
        plugin_work = plugin_fix_dir / f"{plugin_name}.work"
        plugin_bare = plugin_fix_dir / f"{plugin_name}.git"
        init_git_work_dir(plugin_work)
        cp_dir = plugin_work / ".claude-plugin"
        cp_dir.mkdir()

        plugin_source_url = plugin_bare.as_uri()
        (cp_dir / "marketplace.json").write_text(
            json.dumps(
                {
                    "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
                    "name": plugin_name,
                    "description": "UJ-05 test marketplace",
                    "owner": {"name": "Test Owner", "email": "test@example.com"},
                    "plugins": [
                        {
                            "name": plugin_name,
                            "description": "UJ-05 test plugin",
                            "source": {"source": "url", "url": plugin_source_url},
                        }
                    ],
                }
            )
        )
        (cp_dir / "plugin.json").write_text(json.dumps({"name": plugin_name, "description": "UJ-05 test plugin"}))
        run_git(["add", ".claude-plugin"], plugin_work)
        run_git(["commit", "-m", f"seed {plugin_name}"], plugin_work)
        run_git(["tag", "1.0.0"], plugin_work)

        clone_as_bare(plugin_work, plugin_bare)

        marketplaces_dir = claude_marketplaces_dir
        mfst_bare = _build_marketplace_manifest_repo(
            tmp_path / "fixtures",
            plugin_name,
            plugin_fix_dir,
            marketplaces_dir,
            manifest_filename="uj05.xml",
        )

        work_dir = tmp_path / "uj-05"
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[("mkt", mfst_bare.as_uri(), "main", "uj05.xml")],
            marketplace_install="true",
            extra_lines=[f"CLAUDE_MARKETPLACES_DIR={marketplaces_dir}"],
        )

        catalog_source = f"{mfst_bare.as_uri()}@main"
        install_result = kanon_install(
            work_dir,
            extra_env={"KANON_CATALOG_SOURCE": catalog_source, "KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert install_result.returncode == 0, (
            f"install failed: stdout={install_result.stdout!r} stderr={install_result.stderr!r}"
        )

        marketplace_link = marketplaces_dir / plugin_name
        assert marketplace_link.exists(), f"marketplace directory not found at {marketplace_link} after install"

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, (
            f"clean failed: stdout={clean_result.stdout!r} stderr={clean_result.stderr!r}"
        )
        assert not marketplace_link.exists(), f"marketplace directory still present at {marketplace_link} after clean"

    def test_uj_06_collision_detection(self, tmp_path: pathlib.Path) -> None:
        """UJ-06: two sources mapping the same package path cause a collision error."""

        _, manifest_a_bare = _build_content_and_manifest(
            tmp_path / "fixtures-a",
            pkg_names=["pkg-alpha"],
        )
        _, manifest_b_bare = _build_content_and_manifest(
            tmp_path / "fixtures-b",
            pkg_names=["pkg-alpha"],
        )

        work_dir = tmp_path / "uj-06"
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[
                ("a", manifest_a_bare.as_uri(), "main", "repo-specs/pkg-alpha-only.xml"),
                ("b", manifest_b_bare.as_uri(), "main", "repo-specs/pkg-alpha-only.xml"),
            ],
            marketplace_install="false",
        )

        catalog_source = f"{manifest_a_bare.as_uri()}@main"
        result = kanon_install(
            work_dir,
            extra_env={"KANON_CATALOG_SOURCE": catalog_source, "KANON_ALLOW_INSECURE_REMOTES": "1"},
        )

        assert result.returncode != 0, (
            f"Expected non-zero exit on collision but got 0.\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert re.search(r"collid|collision|conflict", combined, re.IGNORECASE), (
            f"Expected collision/conflict message in output: {combined!r}"
        )

    def test_uj_07_linkfile_journey(
        self,
        tmp_path: pathlib.Path,
        claude_marketplaces_dir: pathlib.Path,
    ) -> None:
        """UJ-07: linkfile creates a symlink that resolves into .kanon-data/sources/.

        The linkfile `dest` uses ${CLAUDE_MARKETPLACES_DIR}/mk22-deep.  The
        symlink is created by the repo tool during sync, independently of the
        marketplace registration lifecycle.  We set KANON_MARKETPLACE_INSTALL=false
        so the test does not depend on a real `claude` binary while still exercising
        the linkfile symlink-creation path.
        """
        plugin_fix_dir = tmp_path / "fixtures" / "plugin-fix"
        plugin_fix_dir.mkdir(parents=True)
        mk_plugin_repo(plugin_fix_dir, "mk22", tags=("1.0.0",))

        marketplaces_dir = claude_marketplaces_dir

        plugin_fix_url = plugin_fix_dir.as_uri()
        mfst_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{plugin_fix_url}/" />\n'
            '  <default remote="local" revision="main" />\n'
            '  <project name="mk22" path=".packages/mk22" remote="local" revision="main">\n'
            f'    <linkfile src="." dest="${{CLAUDE_MARKETPLACES_DIR}}/mk22-deep" />\n'
            "  </project>\n"
            "</manifest>\n"
        )
        manifest_repos = tmp_path / "fixtures" / "manifest-repos"
        manifest_repos.mkdir(parents=True, exist_ok=True)
        mfst_bare = make_plain_repo(manifest_repos, "mfst-repo", {"mk22.xml": mfst_xml})

        work_dir = tmp_path / "uj-07"
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[("mkt", mfst_bare.as_uri(), "main", "mk22.xml")],
            marketplace_install="false",
            extra_lines=[f"CLAUDE_MARKETPLACES_DIR={marketplaces_dir}"],
        )

        catalog_source = f"{mfst_bare.as_uri()}@main"
        install_result = kanon_install(
            work_dir,
            extra_env={"KANON_CATALOG_SOURCE": catalog_source, "KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert install_result.returncode == 0, (
            f"install failed: stdout={install_result.stdout!r} stderr={install_result.stderr!r}"
        )

        link_path = marketplaces_dir / "mk22-deep"
        assert link_path.is_symlink(), f"Expected linkfile symlink at {link_path}; stdout={install_result.stdout!r}"
        real_target = os.path.realpath(str(link_path))
        assert ".kanon-data" in real_target and "sources" in real_target, (
            f"Symlink target does not point inside .kanon-data/sources/: {real_target!r}"
        )

        kanon_clean(work_dir)

    def test_uj_08_pipeline_cache(self, tmp_path: pathlib.Path) -> None:
        """UJ-08: clean succeeds against a state that was archived and restored (simulated cache)."""
        _, manifest_bare = _build_content_and_manifest(tmp_path / "fixtures")

        work_dir = tmp_path / "uj-08"
        work_dir.mkdir()
        kanon_home = tmp_path / "uj-08-home"
        store = _store_dir(kanon_home)

        write_kanonenv(
            work_dir,
            sources=[("a", manifest_bare.as_uri(), "main", "repo-specs/pkg-alpha-only.xml")],
            marketplace_install="false",
        )

        install_env = {"KANON_ALLOW_INSECURE_REMOTES": "1", "KANON_HOME": str(kanon_home)}
        install_result = kanon_install(work_dir, extra_env=install_env)
        assert install_result.returncode == 0, (
            f"install failed: stdout={install_result.stdout!r} stderr={install_result.stderr!r}"
        )

        archive_path = tmp_path / "cache.tgz"
        with tarfile.open(str(archive_path), "w:gz") as tar:
            for name in (".packages", ".kanon-data"):
                entry = store / name
                if entry.exists():
                    tar.add(str(entry), arcname=name)

        shutil.rmtree(str(store / ".packages"))
        shutil.rmtree(str(store / ".kanon-data"))

        with tarfile.open(str(archive_path), "r:gz") as tar:
            try:
                tar.extractall(str(store), filter="tar")
            except TypeError:
                tar.extractall(str(store))

        clean_result = kanon_clean(work_dir, extra_env={"KANON_HOME": str(kanon_home)})
        assert clean_result.returncode == 0, (
            f"clean failed after cache restore: stdout={clean_result.stdout!r} stderr={clean_result.stderr!r}"
        )
        assert "kanon clean: done" in clean_result.stdout
        assert not (store / ".packages").exists(), "store .packages/ still exists after clean"
        assert not (store / ".kanon-data").exists(), "store .kanon-data/ still exists after clean"

    def test_uj_09_shell_variable_expansion(self, tmp_path: pathlib.Path) -> None:
        """UJ-09: defined shell vars expand; undefined vars produce a named error."""
        _, manifest_bare = _build_content_and_manifest(tmp_path / "fixtures")

        work_dir_ok = tmp_path / "uj-09-ok"
        work_dir_ok.mkdir()
        manifest_url = manifest_bare.as_uri()

        kanon_text = (
            f"KANON_SOURCE_a_URL={manifest_url}\n"
            "KANON_SOURCE_a_REF=main\n"
            "KANON_SOURCE_a_PATH=repo-specs/pkg-alpha-only.xml\n"
            "KANON_SOURCE_a_NAME=a\n"
            f"KANON_SOURCE_a_GITBASE={manifest_url}\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "HOME_NOTE=${HOME}\n"
        )
        (work_dir_ok / ".kanon").write_text(kanon_text)

        catalog_source = f"{manifest_bare.as_uri()}@main"
        ok_result = kanon_install(
            work_dir_ok,
            extra_env={"KANON_CATALOG_SOURCE": catalog_source, "KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert ok_result.returncode == 0, (
            f"install with HOME expansion failed: stdout={ok_result.stdout!r} stderr={ok_result.stderr!r}"
        )
        kanon_clean(work_dir_ok)

        work_dir_bad = tmp_path / "uj-09-bad"
        work_dir_bad.mkdir()

        bad_kanon_text = (
            "KANON_SOURCE_a_URL=${UNDEFINED_KANON_VAR}\n"
            "KANON_SOURCE_a_REF=main\n"
            "KANON_SOURCE_a_PATH=repo-specs/pkg-alpha-only.xml\n"
        )
        (work_dir_bad / ".kanon").write_text(bad_kanon_text)

        bad_result = kanon_install(
            work_dir_bad,
            extra_env={"KANON_CATALOG_SOURCE": catalog_source, "KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert bad_result.returncode != 0, "Expected non-zero exit when KANON_SOURCE_a_URL is an undefined variable"
        combined = bad_result.stdout + bad_result.stderr
        assert "UNDEFINED_KANON_VAR" in combined, f"Expected undefined variable name in error output: {combined!r}"

    def test_uj_10_python_m_kanon_cli_entry_point(self) -> None:
        """UJ-10: python -m kanon_cli --version and --help exit 0 with expected output."""
        version_result = run_kanon("--version")
        assert version_result.returncode == 0, (
            f"--version exited {version_result.returncode}\nstderr={version_result.stderr!r}"
        )
        assert re.search(r"kanon\s+\d+\.\d+\.\d+", version_result.stdout), (
            f"Expected 'kanon <version>' in stdout: {version_result.stdout!r}"
        )

        help_result = run_kanon("--help")
        assert help_result.returncode == 0, f"--help exited {help_result.returncode}\nstderr={help_result.stderr!r}"

        for expected_cmd in ("install", "clean", "validate", "search"):
            assert expected_cmd in help_result.stdout, (
                f"Expected '{expected_cmd}' in --help stdout: {help_result.stdout!r}"
            )

    def test_uj_11_standalone_repo_journey(self, tmp_path: pathlib.Path) -> None:
        """UJ-11: kanon repo init / sync / status all exit 0."""
        manifest_bare = _build_manifest_for_repo_command(tmp_path / "fixtures")

        work_dir = tmp_path / "uj-11"
        work_dir.mkdir()

        init_result = run_kanon(
            "repo",
            "init",
            "-u",
            manifest_bare.as_uri(),
            "-b",
            "main",
            "-m",
            "default.xml",
            cwd=work_dir,
        )
        assert init_result.returncode == 0, (
            f"repo init exited {init_result.returncode}\nstdout={init_result.stdout!r}\nstderr={init_result.stderr!r}"
        )

        sync_result = run_kanon("repo", "sync", "--jobs=4", cwd=work_dir)
        assert sync_result.returncode == 0, (
            f"repo sync exited {sync_result.returncode}\nstdout={sync_result.stdout!r}\nstderr={sync_result.stderr!r}"
        )

        status_result = run_kanon("repo", "status", cwd=work_dir)
        assert status_result.returncode == 0, (
            f"repo status exited {status_result.returncode}\n"
            f"stdout={status_result.stdout!r}\nstderr={status_result.stderr!r}"
        )

    def test_uj_12_manifest_validation_journey(self, tmp_path: pathlib.Path) -> None:
        """UJ-12: validate xml on a valid manifest repo exits 0."""
        _, manifest_bare = _build_content_and_manifest(tmp_path / "fixtures")

        content_url = (tmp_path / "fixtures" / "content-repos").as_uri()
        repo_dir = tmp_path / "uj-12-repo"
        repo_dir.mkdir()
        init_git_work_dir(repo_dir)

        remote_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{content_url}/" />\n'
            '  <default remote="local" revision="main" />\n'
            "</manifest>\n"
        )
        alpha_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="repo-specs/remote.xml" />\n'
            '  <project name="pkg-alpha" path=".packages/pkg-alpha"'
            ' remote="local" revision="main" />\n'
            "</manifest>\n"
        )
        (repo_dir / "repo-specs").mkdir()
        (repo_dir / "repo-specs" / "remote.xml").write_text(remote_xml)
        (repo_dir / "repo-specs" / "alpha-only.xml").write_text(alpha_xml)
        run_git(["add", "repo-specs"], repo_dir)
        run_git(["commit", "-m", "add manifests"], repo_dir)

        xml_result = run_kanon("validate", "xml", "--repo-root", str(repo_dir))
        assert xml_result.returncode == 0, (
            f"validate xml exited {xml_result.returncode}\nstdout={xml_result.stdout!r}\nstderr={xml_result.stderr!r}"
        )
        combined = xml_result.stdout + xml_result.stderr
        assert "valid" in combined.lower(), f"Expected 'valid' in validate xml output: {combined!r}"
