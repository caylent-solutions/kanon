"""IC (Install/Clean Lifecycle) scenarios from `docs/integration-testing.md` §5.

Each scenario exercises the `kanon install` / `kanon clean` end-to-end lifecycle
against on-disk bare git repos served over `file://` URLs -- no network access
required.

Scenarios automated:
- IC-01: Single source, no marketplace -- install and clean
- IC-02: Shell variable expansion (${HOME})
- IC-03: Comments and blank lines in .kanon
- IC-04: KANON_MARKETPLACE_INSTALL=false explicit
"""

from __future__ import annotations

import os
import pathlib

import pytest

from tests.scenarios.conftest import (
    kanon_clean,
    kanon_install,
    make_plain_repo,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_fixtures(base: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Build the minimal fixture repos needed by all IC scenarios.

    Returns:
        (pkg_alpha_bare, manifest_primary_bare) -- both are bare git repo paths.

    The manifest repo contains:
      - repo-specs/remote.xml -- defines a `local` remote pointing at the
        content-repos directory (parent of pkg_alpha_bare)
      - repo-specs/alpha-only.xml -- includes remote.xml and declares the
        pkg-alpha project at path `.packages/pkg-alpha`
    """
    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    # --- pkg-alpha content repo ---
    pkg_alpha_bare = make_plain_repo(
        content_repos,
        "pkg-alpha",
        {"README.md": "# pkg-alpha\n"},
    )

    # The fetch URL for the manifest remote must point at the *directory*
    # containing the bare repo (repo tool resolves `fetch + name + ".git"`).
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

    # --- manifest-primary bare repo ---
    manifest_primary_bare = make_plain_repo(
        manifest_repos,
        "manifest-primary",
        {
            "repo-specs/remote.xml": remote_xml,
            "repo-specs/alpha-only.xml": alpha_only_xml,
        },
    )

    return pkg_alpha_bare, manifest_primary_bare


def _kanonenv_content(manifest_url: str, *, extra_lines: list[str] | None = None) -> str:
    """Return the text of a minimal .kanon file pointing at the primary manifest."""
    lines = [
        "KANON_MARKETPLACE_INSTALL=false",
        f"KANON_SOURCE_primary_URL={manifest_url}",
        "KANON_SOURCE_primary_REVISION=main",
        "KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml",
    ]
    if extra_lines:
        lines.extend(extra_lines)
    return "\n".join(lines) + "\n"


def _assert_install_pass_criteria(work_dir: pathlib.Path, result) -> None:
    """Assert the standard install pass criteria documented for IC-01..IC-04."""
    assert result.returncode == 0, (
        f"kanon install exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "kanon install: done" in result.stdout, f"'kanon install: done' not in stdout: {result.stdout!r}"
    assert (work_dir / ".kanon-data" / "sources" / "primary").is_dir(), ".kanon-data/sources/primary/ directory missing"
    assert (work_dir / ".packages").is_dir(), ".packages/ directory missing"
    pkg_alpha_link = work_dir / ".packages" / "pkg-alpha"
    assert pkg_alpha_link.is_symlink(), ".packages/pkg-alpha is not a symlink"
    link_target = os.readlink(str(pkg_alpha_link))
    assert ".kanon-data/sources/primary" in link_target or (
        work_dir / ".kanon-data" / "sources" / "primary"
    ).as_posix() in os.path.realpath(str(pkg_alpha_link)), (
        f"symlink target does not reference .kanon-data/sources/primary: {link_target!r}"
    )
    gitignore = work_dir / ".gitignore"
    assert gitignore.exists(), ".gitignore does not exist"
    gitignore_text = gitignore.read_text()
    assert ".packages/" in gitignore_text, ".gitignore missing '.packages/'"
    assert ".kanon-data/" in gitignore_text, ".gitignore missing '.kanon-data/'"


def _assert_clean_pass_criteria(work_dir: pathlib.Path, result) -> None:
    """Assert the standard clean pass criteria documented for IC-01."""
    assert result.returncode == 0, (
        f"kanon clean exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "kanon clean: done" in result.stdout, f"'kanon clean: done' not in stdout: {result.stdout!r}"
    assert not (work_dir / ".packages").exists(), ".packages/ still exists after clean"
    assert not (work_dir / ".kanon-data").exists(), ".kanon-data/ still exists after clean"


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestIC:
    def test_ic_01_single_source_install_and_clean(self, tmp_path: pathlib.Path) -> None:
        """IC-01: Single source, no marketplace -- full install then clean cycle."""
        _, manifest_bare = _build_fixtures(tmp_path / "fixtures")

        work_dir = tmp_path / "test-ic01"
        work_dir.mkdir()

        manifest_url = manifest_bare.as_uri()
        (work_dir / ".kanon").write_text(_kanonenv_content(manifest_url))

        install_result = kanon_install(work_dir)
        _assert_install_pass_criteria(work_dir, install_result)

        clean_result = kanon_clean(work_dir)
        _assert_clean_pass_criteria(work_dir, clean_result)

    def test_ic_02_shell_variable_expansion(self, tmp_path: pathlib.Path) -> None:
        """IC-02: ${HOME} in .kanon is expanded during parsing, not stored expanded."""
        _, manifest_bare = _build_fixtures(tmp_path / "fixtures")

        work_dir = tmp_path / "test-ic02"
        work_dir.mkdir()

        manifest_url = manifest_bare.as_uri()
        kanon_text = (
            "KANON_MARKETPLACE_INSTALL=false\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            f"KANON_SOURCE_primary_URL={manifest_url}\n"
            "KANON_SOURCE_primary_REVISION=main\n"
            "KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml\n"
        )
        kanon_file = work_dir / ".kanon"
        kanon_file.write_text(kanon_text)

        # Verify the literal string is present in the file (not pre-expanded)
        assert "${HOME}" in kanon_file.read_text(), "The .kanon file should contain the literal string '${HOME}'"

        install_result = kanon_install(work_dir)
        assert install_result.returncode == 0, (
            f"kanon install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )
        assert "kanon install: done" in install_result.stdout, (
            f"'kanon install: done' not in stdout: {install_result.stdout!r}"
        )

        kanon_clean(work_dir)

    def test_ic_03_comments_and_blank_lines(self, tmp_path: pathlib.Path) -> None:
        """IC-03: Comments and blank lines in .kanon do not cause parsing errors."""
        _, manifest_bare = _build_fixtures(tmp_path / "fixtures")

        work_dir = tmp_path / "test-ic03"
        work_dir.mkdir()

        manifest_url = manifest_bare.as_uri()
        kanon_text = (
            "# This is a comment\n"
            "# Another comment\n"
            "\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "\n"
            "# Blank lines above and below should be ignored\n"
            "\n"
            f"KANON_SOURCE_primary_URL={manifest_url}\n"
            "KANON_SOURCE_primary_REVISION=main\n"
            "KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml\n"
            "\n"
            "# Trailing comment\n"
        )
        (work_dir / ".kanon").write_text(kanon_text)

        install_result = kanon_install(work_dir)
        assert install_result.returncode == 0, (
            f"kanon install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )
        assert "kanon install: done" in install_result.stdout, (
            f"'kanon install: done' not in stdout: {install_result.stdout!r}"
        )
        pkg_alpha_link = work_dir / ".packages" / "pkg-alpha"
        assert pkg_alpha_link.is_symlink(), (
            ".packages/pkg-alpha symlink missing -- comments/blank lines may have broken parsing"
        )

        kanon_clean(work_dir)

    def test_ic_04_marketplace_install_false_explicit(self, tmp_path: pathlib.Path) -> None:
        """IC-04: KANON_MARKETPLACE_INSTALL=false suppresses marketplace lifecycle output."""
        _, manifest_bare = _build_fixtures(tmp_path / "fixtures")

        work_dir = tmp_path / "test-ic04"
        work_dir.mkdir()

        manifest_url = manifest_bare.as_uri()
        (work_dir / ".kanon").write_text(_kanonenv_content(manifest_url))

        install_result = kanon_install(work_dir)
        assert install_result.returncode == 0, (
            f"kanon install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )
        assert "kanon install: done" in install_result.stdout, (
            f"'kanon install: done' not in stdout: {install_result.stdout!r}"
        )
        # Verify no marketplace lifecycle actions were triggered.  The specific
        # lines printed only when KANON_MARKETPLACE_INSTALL=true are:
        #   "kanon install: preparing marketplace directory..."
        #   "kanon install: installing marketplace plugins..."
        # (The bare word "marketplace" can appear in file paths, so we check
        #  for the action-prefixed strings instead.)
        for marketplace_action in (
            "kanon install: preparing marketplace directory",
            "kanon install: installing marketplace plugins",
        ):
            assert marketplace_action not in install_result.stdout, (
                f"marketplace lifecycle action found in stdout when KANON_MARKETPLACE_INSTALL=false -- "
                f"found {marketplace_action!r} in: {install_result.stdout!r}"
            )

        kanon_clean(work_dir)
