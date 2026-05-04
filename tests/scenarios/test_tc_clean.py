"""TC-clean scenarios from `docs/integration-testing.md` §27.

Each scenario exercises top-level `kanon clean` surface area.

Scenarios automated:
- TC-clean-01: auto-discover clean removes .packages and .kanon-data
- TC-clean-02: .gitignore lines retained after clean
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
class TestTCClean:
    # ------------------------------------------------------------------
    # TC-clean-01: auto-discover clean
    # ------------------------------------------------------------------

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

        install_result = kanon_install(work_dir)
        assert install_result.returncode == 0, (
            f"install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        clean_result = kanon_clean(work_dir)
        assert clean_result.returncode == 0, (
            f"clean exited {clean_result.returncode}\nstdout={clean_result.stdout!r}\nstderr={clean_result.stderr!r}"
        )

        assert not (work_dir / ".packages").exists(), ".packages still present after clean"
        assert not (work_dir / ".kanon-data").exists(), ".kanon-data still present after clean"

    # ------------------------------------------------------------------
    # TC-clean-02: .gitignore lines retained after clean
    # ------------------------------------------------------------------

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

        install_result = kanon_install(work_dir)
        assert install_result.returncode == 0, (
            f"install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        gitignore_path = work_dir / ".gitignore"
        assert gitignore_path.exists(), ".gitignore not created by install"
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
