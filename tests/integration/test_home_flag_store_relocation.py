"""Integration tests for the shared KANON_HOME store under item 12.

Two end-to-end install behaviors are asserted:

1. The removed ``KANON_WORKSPACE_DIR`` and ``KANON_CACHE_DIR`` env vars have NO
   effect: with them set to junk paths, ``install`` still places ``.packages/``
   and ``.kanon-data/`` under ``<KANON_HOME>/store`` and never touches the junk
   paths or the project directory.

2. The ``--home`` global flag, threaded through ``cli.main`` ->
   ``_apply_global_flags`` -> ``KANON_HOME`` env, relocates the store to the
   flag path even when ``KANON_HOME`` env points elsewhere (precedence
   flag > env). Artifacts land under ``<flag-home>/store``, not under the env
   home and not beside ``.kanon``.

Repo / network operations are patched to no-ops so the install runs hermetically
and deterministically.
"""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.cli import main
from kanon_cli.constants import KANON_HOME_STORE_SUBDIR
from kanon_cli.core.include_walker import IncludeTree
from kanon_cli.core.install import _RefResolution, install


_FAKE_SHA = "a" * 40
_FAKE_REF_RESOLUTION = _RefResolution(sha=_FAKE_SHA, resolved_ref="refs/heads/main")


def _store_dir(kanon_home: pathlib.Path) -> pathlib.Path:
    """Return the artifact store directory for a given KANON_HOME root."""
    return kanon_home / KANON_HOME_STORE_SUBDIR


def _url_kanonenv(directory: pathlib.Path, source_name: str = "build") -> pathlib.Path:
    """Write a minimal URL-based .kanon file and return its resolved path."""
    kanonenv = directory / ".kanon"
    kanonenv.write_text(
        f"KANON_SOURCE_{source_name}_URL=https://example.com/{source_name}.git\n"
        f"KANON_SOURCE_{source_name}_REF=main\n"
        f"KANON_SOURCE_{source_name}_PATH=meta.xml\n"
        f"KANON_SOURCE_{source_name}_NAME={source_name}\n"
        f"KANON_SOURCE_{source_name}_GITBASE=https://example.com\n",
        encoding="utf-8",
    )
    return kanonenv.resolve()


def _install_patches() -> tuple:
    """Return the context-manager patches that make install() hermetic."""
    return (
        patch("kanon_cli.repo.repo_init"),
        patch("kanon_cli.repo.repo_envsubst"),
        patch("kanon_cli.repo.repo_sync"),
        patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=_FAKE_REF_RESOLUTION),
        patch(
            "kanon_cli.core.install._walk_includes",
            return_value=IncludeTree(path=pathlib.Path("meta.xml")),
        ),
    )


def _run_install_direct(kanonenv: pathlib.Path, lock_path: pathlib.Path) -> None:
    """Run install() directly with repo operations patched to no-ops."""
    p_init, p_env, p_sync, p_ref, p_walk = _install_patches()
    with p_init, p_env, p_sync, p_ref, p_walk:
        install(kanonenv, lock_file_path=lock_path)


@pytest.mark.integration
class TestRemovedVarsHaveNoEffect:
    """KANON_WORKSPACE_DIR / KANON_CACHE_DIR are removed: junk values do nothing."""

    def test_junk_removed_vars_do_not_relocate_store(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Artifacts land under <KANON_HOME>/store regardless of the removed vars."""
        kanon_home = tmp_path / "kanon_home"
        store = _store_dir(kanon_home)
        junk_workspace = tmp_path / "junk_workspace"
        junk_cache = tmp_path / "junk_cache"
        project = tmp_path / "project"
        project.mkdir()

        monkeypatch.setenv("KANON_HOME", str(kanon_home))
        monkeypatch.setenv("KANON_WORKSPACE_DIR", str(junk_workspace))
        monkeypatch.setenv("KANON_CACHE_DIR", str(junk_cache))

        kanonenv = _url_kanonenv(project)
        lock_path = project / ".kanon.lock"

        _run_install_direct(kanonenv, lock_path)

        assert (store / ".kanon-data").exists(), "install must place .kanon-data/ under <KANON_HOME>/store"
        assert (store / ".packages").exists(), "install must place .packages/ under <KANON_HOME>/store"
        assert not junk_workspace.exists(), "KANON_WORKSPACE_DIR is removed and must have no effect"
        assert not junk_cache.exists(), "KANON_CACHE_DIR is removed and must have no effect"
        assert not (project / ".packages").exists(), "install must NOT write artifacts beside .kanon"
        assert not (project / ".kanon-data").exists(), "install must NOT write artifacts beside .kanon"


@pytest.mark.integration
class TestHomeFlagRelocatesStoreEndToEnd:
    """The --home flag (via cli.main) wins over KANON_HOME env for the store path."""

    def test_home_flag_wins_over_env_for_store(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """kanon --home <flag> install places artifacts under <flag>/store, not <env>/store."""
        flag_home = tmp_path / "flag_home"
        env_home = tmp_path / "env_home"
        flag_store = _store_dir(flag_home)
        env_store = _store_dir(env_home)
        project = tmp_path / "project"
        project.mkdir()

        monkeypatch.setenv("KANON_HOME", str(env_home))
        monkeypatch.setenv("KANON_SKIP_UPDATE_CHECK", "1")

        kanonenv = _url_kanonenv(project)

        p_init, p_env, p_sync, p_ref, p_walk = _install_patches()
        with p_init, p_env, p_sync, p_ref, p_walk:
            main(["--home", str(flag_home), "install", str(kanonenv)])

        assert (flag_store / ".kanon-data").exists(), "--home must relocate the store to the flag path"
        assert (flag_store / ".packages").exists(), "--home must relocate the store to the flag path"
        assert not env_store.exists(), "the KANON_HOME env store must be unused when --home is given"
        assert not (project / ".packages").exists(), "install must NOT write artifacts beside .kanon"
