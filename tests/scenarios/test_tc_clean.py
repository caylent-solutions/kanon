"""TC-clean scenarios from `docs/integration-testing.md` §27.

Each scenario exercises top-level `kanon clean` surface area.

Scenarios automated:
- TC-clean-01: auto-discover clean removes .packages and .kanon-data
- TC-clean-02: .gitignore lines retained after clean
- TC-clean-03: `clean --orphans` prunes the marketplace of a source removed
  from .kanon (orphaned source). Installs two marketplace sources, `kanon
  remove`s one, then `clean --orphans` unregisters the removed source's
  marketplace while leaving the still-referenced source's marketplace. The
  marketplace unregistration goes through the real `claude` CLI, so the test is
  guarded with `pytest.skip()` when the `claude` binary is absent.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil

import pytest

from tests.scenarios.conftest import (
    clone_as_bare,
    init_git_work_dir,
    kanon_clean,
    kanon_install,
    make_plain_repo,
    run_git,
    run_kanon,
    write_kanonenv,
)


def _build_manifest_fixture(base: pathlib.Path) -> pathlib.Path:
    """Build a bare manifest repo containing repo-specs/alpha-only.xml.

    Returns the bare manifest repo path so callers can reference it in
    KANON_SOURCE_*_URL.
    """
    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    make_plain_repo(content_repos, "pkg-alpha", {"README.md": "# pkg-alpha\n"})
    content_url = content_repos.as_uri()

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

    return make_plain_repo(
        manifest_repos,
        "manifest-primary",
        {
            "repo-specs/remote.xml": remote_xml,
            "repo-specs/alpha-only.xml": alpha_xml,
        },
    )


@pytest.mark.scenario
class TestTCClean:
    def test_tc_clean_01_auto_discover_removes_dirs(self, tmp_path: pathlib.Path) -> None:
        """TC-clean-01: kanon clean removes .packages and .kanon-data."""
        manifest_bare = _build_manifest_fixture(tmp_path / "fixtures")

        work_dir = tmp_path / "tc-cln-01"
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[
                (
                    "a",
                    manifest_bare.as_uri(),
                    "main",
                    "repo-specs/alpha-only.xml",
                )
            ],
            marketplace_install="false",
        )

        catalog_source = f"{manifest_bare.as_uri()}@main"
        install_result = kanon_install(
            work_dir,
            extra_env={"KANON_CATALOG_SOURCE": catalog_source, "KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert install_result.returncode == 0, (
            f"install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, (
            f"clean exited {clean_result.returncode}\nstdout={clean_result.stdout!r}\nstderr={clean_result.stderr!r}"
        )

        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        assert not (store_base / ".packages").exists(), ".packages still present in store after clean"
        assert not (store_base / ".kanon-data").exists(), ".kanon-data still present in store after clean"

    def test_tc_clean_02_gitignore_lines_retained(self, tmp_path: pathlib.Path) -> None:
        """TC-clean-02: .gitignore entries written by install remain after clean."""
        manifest_bare = _build_manifest_fixture(tmp_path / "fixtures")

        work_dir = tmp_path / "tc-cln-02"
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[
                (
                    "a",
                    manifest_bare.as_uri(),
                    "main",
                    "repo-specs/alpha-only.xml",
                )
            ],
            marketplace_install="false",
        )

        catalog_source = f"{manifest_bare.as_uri()}@main"
        install_result = kanon_install(
            work_dir,
            extra_env={"KANON_CATALOG_SOURCE": catalog_source, "KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert install_result.returncode == 0, (
            f"install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        gitignore_path = store_base / ".gitignore"
        assert gitignore_path.exists(), ".gitignore not created by install in store"
        install_gitignore = gitignore_path.read_text()
        assert ".packages/" in install_gitignore, (
            f".packages/ not found in .gitignore after install: {install_gitignore!r}"
        )

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, f"clean exited {clean_result.returncode}\nstdout={clean_result.stdout!r}"

        post_clean_gitignore = gitignore_path.read_text()
        assert ".packages/" in post_clean_gitignore, (
            f".packages/ line removed from .gitignore after clean: {post_clean_gitignore!r}"
        )
        assert ".kanon-data/" in post_clean_gitignore, (
            f".kanon-data/ line removed from .gitignore after clean: {post_clean_gitignore!r}"
        )

    def _build_marketplace_plugin(self, plugins: pathlib.Path, name: str) -> None:
        """Seed a bare plugin repo named ``name`` carrying a claude-schema marketplace.json.

        The real ``claude`` CLI rejects a marketplace.json lacking the ``owner``
        object, so the full schema (mirroring the MK fixtures) is required for
        ``claude plugin marketplace add`` to succeed.
        """
        work = plugins / f"{name}.work"
        bare = plugins / f"{name}.git"
        init_git_work_dir(work)
        cp = work / ".claude-plugin"
        cp.mkdir()
        (cp / "marketplace.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "owner": {"name": "Test", "url": "https://example.com"},
                    "metadata": {"description": "synthetic test marketplace", "version": "0.1.0"},
                    "plugins": [{"name": name, "source": "./", "description": f"synthetic plugin {name}"}],
                }
            )
        )
        (cp / "plugin.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "version": "0.1.0",
                    "description": "synthetic test plugin",
                    "author": {"name": "Test", "url": "https://example.com"},
                    "keywords": ["test"],
                }
            )
        )
        run_git(["add", "."], work)
        run_git(["commit", "-m", f"seed {name}"], work)
        clone_as_bare(work, bare)

    def _build_two_marketplace_sources(self, base: pathlib.Path, marketplaces_dir: pathlib.Path) -> pathlib.Path:
        """Build a bare manifest repo with two marketplace-bearing source manifests.

        ``repo-specs/orphan-only.xml`` deposits marketplace ``orphan-mp`` and
        ``repo-specs/keep-only.xml`` deposits marketplace ``keep-mp``, each via a
        ``<linkfile>``.  After installing both, the lockfile attributes
        ``orphan-mp`` to the orphan source and ``keep-mp`` to the keep source.
        """
        plugins = base / "plugins"
        plugins.mkdir(parents=True)
        self._build_marketplace_plugin(plugins, "orphan-mp")
        self._build_marketplace_plugin(plugins, "keep-mp")

        remote_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="local" fetch="{plugins.as_uri()}/" />\n'
            '  <default remote="local" revision="main" />\n'
            "</manifest>\n"
        )

        def _mp_manifest(name: str) -> str:
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <include name="repo-specs/remote.xml" />\n'
                f'  <project name="{name}" path=".packages/{name}" remote="local" revision="main">\n'
                f'    <linkfile src="." dest="{marketplaces_dir}/{name}" />\n'
                "  </project>\n"
                "</manifest>\n"
            )

        return make_plain_repo(
            base / "manifest-repos",
            "manifest-mp",
            {
                "repo-specs/remote.xml": remote_xml,
                "repo-specs/orphan-only.xml": _mp_manifest("orphan-mp"),
                "repo-specs/keep-only.xml": _mp_manifest("keep-mp"),
            },
        )

    def test_tc_clean_03_orphans_prunes_removed_source_marketplace(self, tmp_path: pathlib.Path) -> None:
        """TC-clean-03: clean --orphans unregisters the marketplace of a source removed from .kanon.

        Installs two marketplace sources (lockfile attributes ``orphan-mp`` to the
        orphan source and ``keep-mp`` to the keep source), runs ``kanon remove`` on
        the orphan source, then ``kanon clean --orphans``.  The orphaned source's
        marketplace (``orphan-mp``) must be unregistered; ``keep-mp`` (still
        referenced) must NOT be.  No manual marketplace-dir deletion is needed.

        The marketplace unregistration goes through the real ``claude`` CLI; when
        ``claude`` is absent the prune step cannot run, so the test skips after
        verifying the no-claude precondition (mirrors the MK skip guard).
        """
        if shutil.which("claude") is None:
            pytest.skip(
                "claude CLI not found on PATH; skipping TC-clean-03 'claude plugin marketplace "
                "remove' verification (no-claude environment cannot exercise the prune path)"
            )

        marketplaces_dir = tmp_path / "claude-marketplaces"
        marketplaces_dir.mkdir()
        manifest_bare = self._build_two_marketplace_sources(tmp_path / "fixtures", marketplaces_dir)

        work_dir = tmp_path / "tc-cln-03"
        work_dir.mkdir()

        write_kanonenv(
            work_dir,
            sources=[
                ("orphan", manifest_bare.as_uri(), "main", "repo-specs/orphan-only.xml"),
                ("keep", manifest_bare.as_uri(), "main", "repo-specs/keep-only.xml"),
            ],
            marketplace_aliases=["orphan", "keep"],
            extra_lines=[f"CLAUDE_MARKETPLACES_DIR={marketplaces_dir}"],
        )

        catalog_source = f"{manifest_bare.as_uri()}@main"
        install_result = kanon_install(
            work_dir,
            extra_env={"KANON_CATALOG_SOURCE": catalog_source, "KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert install_result.returncode == 0, (
            f"TC-clean-03 install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        assert (marketplaces_dir / "orphan-mp").exists(), (
            f"TC-clean-03: expected marketplace entry orphan-mp; install stdout={install_result.stdout!r}"
        )
        assert (marketplaces_dir / "keep-mp").exists(), (
            f"TC-clean-03: expected marketplace entry keep-mp; install stdout={install_result.stdout!r}"
        )

        remove_result = run_kanon("remove", "orphan", cwd=work_dir)
        assert remove_result.returncode == 0, (
            f"TC-clean-03 remove exited {remove_result.returncode}\n"
            f"stdout={remove_result.stdout!r}\nstderr={remove_result.stderr!r}"
        )

        clean_result = run_kanon("clean", "--orphans", cwd=work_dir)
        assert clean_result.returncode == 0, (
            f"TC-clean-03 clean --orphans exited {clean_result.returncode}\n"
            f"stdout={clean_result.stdout!r}\nstderr={clean_result.stderr!r}"
        )

        prune_lines = [
            line.strip()
            for line in clean_result.stdout.splitlines()
            if line.strip().startswith("- unregistering marketplace:")
        ]
        assert "- unregistering marketplace: orphan-mp" in prune_lines, (
            f"TC-clean-03: expected the prune to unregister 'orphan-mp'; prune lines={prune_lines!r}"
        )
        assert "- unregistering marketplace: keep-mp" not in prune_lines, (
            f"TC-clean-03: keep-mp is still referenced and must NOT be pruned; prune lines={prune_lines!r}"
        )
        store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
        assert not (store_base / ".packages").exists(), (
            "TC-clean-03: .packages still present in store after clean --orphans"
        )
        assert not (store_base / ".kanon-data").exists(), (
            "TC-clean-03: .kanon-data still present in store after clean --orphans"
        )
