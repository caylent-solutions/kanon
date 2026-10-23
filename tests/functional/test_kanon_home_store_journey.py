"""Shared KANON_HOME gitignore safety for installs inside and outside a repository.

Real workspace isolation and legacy snapshot cleanup are covered by
``tests/scenarios/test_shared_home_storage.py``.
"""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.constants import KANON_HOME_STORE_GITIGNORE_ENTRY
from kanon_cli.core.include_walker import IncludeTree
from kanon_cli.core.install import install


_SOURCE_URL = "https://example.com/build.git"
_SOURCE_SHA = "a" * 40

_KANONENV = (
    f"KANON_SOURCE_build_URL={_SOURCE_URL}\n"
    "KANON_SOURCE_build_REF=main\n"
    "KANON_SOURCE_build_PATH=meta.xml\n"
    "KANON_SOURCE_build_NAME=build\n"
    "KANON_SOURCE_build_GITBASE=https://example.com\n"
)


def _write_kanonenv(project_dir: pathlib.Path) -> pathlib.Path:
    """Create a project dir with a minimal single-source ``.kanon`` and return it."""
    project_dir.mkdir(parents=True, exist_ok=True)
    kanonenv = project_dir / ".kanon"
    kanonenv.write_text(_KANONENV, encoding="utf-8")
    return kanonenv


def _install_project(project_dir: pathlib.Path) -> None:
    """Run ``install`` against ``project_dir`` with the repo sub-commands patched.

    ``repo init/envsubst/sync`` and the ref resolver are patched so the journey
    is deterministic and offline; workspace creation and conditional .gitignore
    writes run unpatched against the real filesystem.
    """
    from kanon_cli.core.install import _RefResolution

    kanonenv = _write_kanonenv(project_dir)
    lock_path = project_dir / ".kanon.lock"
    with (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
        patch("kanon_cli.core.install.collect_manifest_projects", return_value=[]),
        patch(
            "kanon_cli.core.install._resolve_ref_to_sha",
            return_value=_RefResolution(sha=_SOURCE_SHA, resolved_ref="refs/heads/main"),
        ),
        patch(
            "kanon_cli.core.install._walk_includes",
            return_value=IncludeTree(path=pathlib.Path("meta.xml")),
        ),
    ):
        install(kanonenv, lock_file_path=lock_path)


@pytest.mark.functional
class TestKanonHomeStoreJourney:
    """The shared store is ignored only when it sits inside a Git repository."""

    def test_conditional_gitignore_written_inside_git_repo(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A .gitignore safety net is written into the store only when KANON_HOME is in a git repo."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        kanon_home = repo_root / "home"
        store = kanon_home / "store"
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        _install_project(tmp_path / "project-in-repo")

        gitignore = store / ".gitignore"
        assert gitignore.is_file(), "a .gitignore must be written when KANON_HOME is inside a git repo"
        lines = gitignore.read_text(encoding="utf-8").splitlines()
        assert KANON_HOME_STORE_GITIGNORE_ENTRY in lines, (
            "the whole-store ignore entry must be present when KANON_HOME is inside a git repo"
        )

    def test_no_whole_store_ignore_when_kanon_home_outside_git_repo(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole-store ignore entry is NOT written when KANON_HOME is not inside a git repo."""
        kanon_home = tmp_path / "plain_home"
        store = kanon_home / "store"
        monkeypatch.setenv("KANON_HOME", str(kanon_home))

        assert not any((parent / ".git").exists() for parent in [store, *store.parents]), (
            "test setup invariant: the store must not sit inside a git repo"
        )

        _install_project(tmp_path / "project-plain")

        gitignore = store / ".gitignore"
        if gitignore.exists():
            lines = gitignore.read_text(encoding="utf-8").splitlines()
            assert KANON_HOME_STORE_GITIGNORE_ENTRY not in lines, (
                "the whole-store ignore safety net must not be written outside a git repo"
            )
