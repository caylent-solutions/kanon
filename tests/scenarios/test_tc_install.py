"""TC-install scenarios from `docs/integration-testing.md` §27.

Each scenario exercises top-level `kanon install` surface area.

Scenarios automated:
- TC-install-01: auto-discover walks parent tree
- TC-install-02: explicit path bypasses auto-discover
- TC-install-03: REPO_URL env emits deprecation warning
- TC-install-04: REPO_REV env emits deprecation warning
"""

from __future__ import annotations

import os
import pathlib

import pytest

from tests.scenarios.conftest import (
    kanon_clean,
    make_plain_repo,
    run_kanon,
    write_kanonenv,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestTCInstall:
    # ------------------------------------------------------------------
    # TC-install-01: auto-discover walks parent tree
    # ------------------------------------------------------------------

    def test_tc_install_01_auto_discover_walks_parent_tree(self, tmp_path: pathlib.Path) -> None:
        """TC-install-01: install from a subdirectory discovers .kanon in the parent tree."""
        manifest_bare = _build_manifest_fixture(tmp_path / "fixtures")

        project_root = tmp_path / "tc-inst-01"
        project_root.mkdir()

        write_kanonenv(
            project_root,
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

        # Run install from a deep subdirectory; auto-discover must walk up.
        sub_deep = project_root / "sub" / "deep"
        sub_deep.mkdir(parents=True)

        install_result = run_kanon("install", cwd=sub_deep)
        assert install_result.returncode == 0, (
            f"install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )
        assert (project_root / ".packages" / "pkg-alpha").is_symlink(), (
            ".packages/pkg-alpha symlink not found in project root"
        )

        clean_result = kanon_clean(project_root)
        assert clean_result.returncode == 0, f"clean exited {clean_result.returncode}\nstdout={clean_result.stdout!r}"

    # ------------------------------------------------------------------
    # TC-install-02: explicit path bypasses auto-discover
    # ------------------------------------------------------------------

    def test_tc_install_02_explicit_path_bypasses_auto_discover(self, tmp_path: pathlib.Path) -> None:
        """TC-install-02: kanon install <path> uses the explicit env file, not auto-discover."""
        manifest_bare = _build_manifest_fixture(tmp_path / "fixtures")

        work_dir = tmp_path / "tc-inst-02"
        work_dir.mkdir()

        kanon_file = work_dir / "my.kanon"
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
        # Rename .kanon to my.kanon so auto-discover cannot find it.
        (work_dir / ".kanon").rename(kanon_file)

        install_result = run_kanon("install", str(kanon_file), cwd=work_dir)
        assert install_result.returncode == 0, (
            f"install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )
        assert (work_dir / ".packages" / "pkg-alpha").is_symlink(), (
            ".packages/pkg-alpha symlink not found after explicit-path install"
        )

        clean_result = run_kanon("clean", str(kanon_file), cwd=work_dir)
        assert clean_result.returncode == 0, f"clean exited {clean_result.returncode}\nstdout={clean_result.stdout!r}"

    # ------------------------------------------------------------------
    # TC-install-03: REPO_URL env emits deprecation warning
    # ------------------------------------------------------------------

    def test_tc_install_03_repo_url_deprecation_warning(self, tmp_path: pathlib.Path) -> None:
        """TC-install-03: kanon install emits a deprecation warning when REPO_URL is set."""
        manifest_bare = _build_manifest_fixture(tmp_path / "fixtures")

        work_dir = tmp_path / "tc-inst-03"
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

        env = dict(os.environ)
        env["REPO_URL"] = "https://example.com/repo.git"

        install_result = run_kanon("install", ".kanon", cwd=work_dir, env=env)
        assert install_result.returncode == 0, (
            f"install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )
        combined = install_result.stdout + install_result.stderr
        assert "deprecat" in combined.lower(), (
            f"Expected a deprecation warning mentioning REPO_URL in output: {combined!r}"
        )

        kanon_clean(work_dir)

    # ------------------------------------------------------------------
    # TC-install-04: REPO_REV env emits deprecation warning
    # ------------------------------------------------------------------

    def test_tc_install_04_repo_rev_deprecation_warning(self, tmp_path: pathlib.Path) -> None:
        """TC-install-04: kanon install emits a deprecation warning when REPO_REV is set."""
        manifest_bare = _build_manifest_fixture(tmp_path / "fixtures")

        work_dir = tmp_path / "tc-inst-04"
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

        env = dict(os.environ)
        env["REPO_REV"] = "v1.2.3"

        install_result = run_kanon("install", ".kanon", cwd=work_dir, env=env)
        assert install_result.returncode == 0, (
            f"install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )
        combined = install_result.stdout + install_result.stderr
        assert "deprecat" in combined.lower(), (
            f"Expected a deprecation warning mentioning REPO_REV in output: {combined!r}"
        )

        kanon_clean(work_dir)
