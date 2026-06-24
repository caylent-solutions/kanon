"""Integration tests for the marketplace orphan-prune lifecycle bugfix.

Covers three behaviours of the PER-SOURCE marketplace attribution model:

(a) ``kanon clean --orphans`` unregisters the marketplaces of a source recorded
    in ``.kanon.lock`` that is no longer declared in the current ``.kanon`` (an
    orphaned source).  A marketplace still provided by a referenced source, and
    any user/keep-set marketplace (never written to any per-source ledger), must
    NOT be removed.

(b) ``kanon install`` auto-prunes: when a source whose marketplace was
    registered is reconciled away (``.kanon`` rewritten from source A to source
    B), source A's marketplace is unregistered via
    ``claude plugin marketplace remove`` and the rewritten lock records each
    surviving source's per-source ledger.

(c) Canonical flow: install A+B, ``kanon remove A`` (no reinstall), then
    ``kanon clean --orphans`` -> A's marketplace is unregistered, B's and the
    keep-set are not.

All tests use the claude-CLI mock pattern: patch
``kanon_cli.core.marketplace.shutil.which`` so ``locate_claude_binary``
succeeds, and patch ``kanon_cli.core.marketplace.subprocess.run`` to record
argv without executing the binary.
"""

from __future__ import annotations

import pathlib
import subprocess
import textwrap
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.install import install
from kanon_cli.core.lockfile import (
    read_lockfile,
)
from tests.integration.test_add_core import _create_manifest_repo_with_tags


_KEEP_SET_NAMES = ("claude-plugins-official", "devbench-authoring")

_MARKETPLACE_JSON_TEMPLATE = '{{"name": "{name}", "plugins": []}}'


def _extract_marketplace_remove_names(call_args_list: list) -> list[str]:
    """Return the marketplace names from each ``claude plugin marketplace remove <name>`` call."""
    names: list[str] = []
    for recorded_call in call_args_list:
        if not recorded_call.args:
            continue
        argv = tuple(str(a) for a in recorded_call.args[0])
        if len(argv) >= 5 and argv[1:4] == ("plugin", "marketplace", "remove"):
            names.append(argv[4])
    return names


_MANIFEST_WITH_LINKFILE_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <project name="{name}" path="{name}" remote="origin" revision="main">
        <linkfile src=".claude-plugin/marketplace.json"
                  dest="{marketplace_dest}/.claude-plugin/marketplace.json" />
      </project>
    </manifest>
""")


def _make_repo_init_with_linkfiles(marketplace_dir: pathlib.Path) -> object:
    """Return a fake repo_init side-effect that writes a manifest + linkfile src per source.

    Mirrors ``tests/integration/test_install_marketplace_registration._make_repo_init_with_linkfiles``:
    the manifest declares a ``<linkfile>`` whose ``dest`` lands the marketplace
    manifest under ``marketplace_dir/<source-name>``, and the linkfile ``src``
    file is written into the simulated checkout so install's
    ``_process_manifest_linkfiles`` can copy it.  The marketplace ``name`` equals
    the source name.
    """

    def fake_repo_init(
        repo_dir: str,
        url: str,
        revision: str,
        manifest_path: str,
        repo_rev: str = "",
    ) -> None:
        manifest_file = pathlib.Path(repo_dir) / ".repo" / "manifests" / manifest_path
        manifest_file.parent.mkdir(parents=True, exist_ok=True)

        stem = pathlib.Path(manifest_path).name
        if stem.endswith("-marketplace.xml"):
            source_name = stem[: -len("-marketplace.xml")]
        else:
            source_name = stem.replace(".xml", "")

        marketplace_dest = marketplace_dir / source_name
        manifest_file.write_text(
            _MANIFEST_WITH_LINKFILE_TEMPLATE.format(
                name=source_name,
                marketplace_dest=str(marketplace_dest),
            )
        )

        src_file = pathlib.Path(repo_dir) / source_name / ".claude-plugin" / "marketplace.json"
        src_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.write_text(_MARKETPLACE_JSON_TEMPLATE.format(name=source_name))

    return fake_repo_init


def _write_kanonenv_single_source(
    directory: pathlib.Path,
    marketplace_dir: pathlib.Path,
    source_name: str,
    source_url: str,
) -> pathlib.Path:
    """Write a .kanon declaring exactly one marketplace-bearing source.

    3.0.0: the source opts into the marketplace via its per-dependency
    KANON_SOURCE_<alias>_MARKETPLACE flag (the removed global
    KANON_MARKETPLACE_INSTALL header no longer exists).
    """
    directory.mkdir(parents=True, exist_ok=True)
    kanonenv = directory / ".kanon"
    kanonenv.write_text(
        f"CLAUDE_MARKETPLACES_DIR={marketplace_dir}\n"
        f"KANON_SOURCE_{source_name}_URL={source_url}\n"
        f"KANON_SOURCE_{source_name}_REF=main\n"
        f"KANON_SOURCE_{source_name}_PATH=repo-specs/{source_name}-marketplace.xml\n"
        f"KANON_SOURCE_{source_name}_NAME={source_name}\n"
        f"KANON_SOURCE_{source_name}_GITBASE=https://example.com\n"
        f"KANON_SOURCE_{source_name}_MARKETPLACE=true\n"
    )
    return kanonenv.resolve()


def _write_kanonenv_sources(
    directory: pathlib.Path,
    marketplace_dir: pathlib.Path,
    sources: list[tuple[str, str]],
) -> pathlib.Path:
    """Write a .kanon declaring each (source_name, source_url) marketplace-bearing source.

    3.0.0: each source opts into the marketplace via its per-dependency
    KANON_SOURCE_<alias>_MARKETPLACE flag (the removed global
    KANON_MARKETPLACE_INSTALL header no longer exists).
    """
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        f"CLAUDE_MARKETPLACES_DIR={marketplace_dir}",
    ]
    for source_name, source_url in sources:
        lines.append(f"KANON_SOURCE_{source_name}_URL={source_url}")
        lines.append(f"KANON_SOURCE_{source_name}_REF=main")
        lines.append(f"KANON_SOURCE_{source_name}_PATH=repo-specs/{source_name}-marketplace.xml")
        lines.append(f"KANON_SOURCE_{source_name}_NAME={source_name}")
        lines.append(f"KANON_SOURCE_{source_name}_GITBASE=https://example.com")
        lines.append(f"KANON_SOURCE_{source_name}_MARKETPLACE=true")
    kanonenv = directory / ".kanon"
    kanonenv.write_text("\n".join(lines) + "\n")
    return kanonenv.resolve()


@pytest.mark.integration
class TestInstallAutoPruneReconcile:
    def test_reconcile_from_a_to_b_unregisters_a_marketplace(self, tmp_path: pathlib.Path) -> None:
        """Install source A (mp recorded), rewrite .kanon to B, reconcile -> A's mp unregistered.

        After the reconcile install, the recorded claude argv must include
        ``marketplace remove source_alpha`` (A's marketplace) and the rewritten
        lockfile's single source B must carry per-source ledger ``[source_bravo]``.
        """
        marketplace_dir = tmp_path / "marketplace"
        marketplace_dir.mkdir()

        bare_alpha = _create_manifest_repo_with_tags(
            tmp_path / "repo-alpha",
            entry_names=["source-alpha"],
            tags=["1.0.0"],
        )
        bare_bravo = _create_manifest_repo_with_tags(
            tmp_path / "repo-bravo",
            entry_names=["source-bravo"],
            tags=["1.0.0"],
        )

        workspace = tmp_path / "workspace"
        lock_path = workspace / ".kanon.lock"
        claude_bin = "/usr/bin/claude"
        mock_completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        kanonenv = _write_kanonenv_single_source(
            workspace,
            marketplace_dir,
            source_name="source_alpha",
            source_url=f"file://{bare_alpha}",
        )

        with (
            patch("kanon_cli.repo.repo_init", side_effect=_make_repo_init_with_linkfiles(marketplace_dir)),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.marketplace.shutil.which", return_value=claude_bin),
            patch("kanon_cli.core.marketplace.subprocess.run", return_value=mock_completed),
        ):
            install(kanonenv, lock_file_path=lock_path)

        first_lock = read_lockfile(lock_path)
        assert len(first_lock.sources) == 1
        assert first_lock.sources[0].registered_marketplaces == ["source_alpha"], (
            f"First install must attribute ['source_alpha'] to source A; "
            f"got {first_lock.sources[0].registered_marketplaces!r}"
        )

        kanonenv = _write_kanonenv_single_source(
            workspace,
            marketplace_dir,
            source_name="source_bravo",
            source_url=f"file://{bare_bravo}",
        )

        with (
            patch("kanon_cli.repo.repo_init", side_effect=_make_repo_init_with_linkfiles(marketplace_dir)),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.marketplace.shutil.which", return_value=claude_bin),
            patch("kanon_cli.core.marketplace.subprocess.run", return_value=mock_completed) as mock_run,
        ):
            install(kanonenv, lock_file_path=lock_path)

        removed = _extract_marketplace_remove_names(mock_run.call_args_list)
        assert "source_alpha" in removed, (
            f"Reconcile install must unregister source A's marketplace 'source_alpha' via "
            f"'claude plugin marketplace remove'; recorded removes: {removed!r}"
        )
        assert "source_bravo" not in removed, (
            f"The freshly-installed marketplace 'source_bravo' must NOT be removed; recorded removes: {removed!r}"
        )

        second_lock = read_lockfile(lock_path)
        assert len(second_lock.sources) == 1
        assert second_lock.sources[0].name == "source_bravo"
        assert second_lock.sources[0].registered_marketplaces == ["source_bravo"], (
            f"After reconcile, source B must carry per-source ledger ['source_bravo']; "
            f"got {second_lock.sources[0].registered_marketplaces!r}"
        )

    def test_install_attributes_marketplaces_per_source(self, tmp_path: pathlib.Path) -> None:
        """Install A+B together -> lock source A has [source_alpha], source B has [source_bravo]."""
        marketplace_dir = tmp_path / "marketplace"
        marketplace_dir.mkdir()

        bare_alpha = _create_manifest_repo_with_tags(
            tmp_path / "repo-alpha",
            entry_names=["source-alpha"],
            tags=["1.0.0"],
        )
        bare_bravo = _create_manifest_repo_with_tags(
            tmp_path / "repo-bravo",
            entry_names=["source-bravo"],
            tags=["1.0.0"],
        )

        workspace = tmp_path / "workspace"
        lock_path = workspace / ".kanon.lock"
        claude_bin = "/usr/bin/claude"
        mock_completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        kanonenv = _write_kanonenv_sources(
            workspace,
            marketplace_dir,
            sources=[
                ("source_alpha", f"file://{bare_alpha}"),
                ("source_bravo", f"file://{bare_bravo}"),
            ],
        )

        with (
            patch("kanon_cli.repo.repo_init", side_effect=_make_repo_init_with_linkfiles(marketplace_dir)),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.marketplace.shutil.which", return_value=claude_bin),
            patch("kanon_cli.core.marketplace.subprocess.run", return_value=mock_completed),
        ):
            install(kanonenv, lock_file_path=lock_path)

        lock = read_lockfile(lock_path)
        by_name = {s.name: s for s in lock.sources}
        assert by_name["source_alpha"].registered_marketplaces == ["source_alpha"], (
            f"source A must be attributed only its own marketplace; "
            f"got {by_name['source_alpha'].registered_marketplaces!r}"
        )
        assert by_name["source_bravo"].registered_marketplaces == ["source_bravo"], (
            f"source B must be attributed only its own marketplace; "
            f"got {by_name['source_bravo'].registered_marketplaces!r}"
        )


@pytest.mark.integration
class TestCleanOrphansCanonicalFlow:
    def test_remove_a_then_clean_orphans_unregisters_a_marketplace(self, tmp_path: pathlib.Path) -> None:
        """Install A+B, ``kanon remove`` source A, then ``clean --orphans`` -> only A's mp removed.

        After removing source A from .kanon (no reinstall), the lock still records
        A with its per-source ledger.  ``clean --orphans`` must unregister A's
        marketplace via ``claude plugin marketplace remove`` and must NOT remove
        B's marketplace nor any keep-set name.
        """
        marketplace_dir = tmp_path / "marketplace"
        marketplace_dir.mkdir()

        bare_alpha = _create_manifest_repo_with_tags(
            tmp_path / "repo-alpha",
            entry_names=["source-alpha"],
            tags=["1.0.0"],
        )
        bare_bravo = _create_manifest_repo_with_tags(
            tmp_path / "repo-bravo",
            entry_names=["source-bravo"],
            tags=["1.0.0"],
        )

        workspace = tmp_path / "workspace"
        lock_path = workspace / ".kanon.lock"
        claude_bin = "/usr/bin/claude"
        mock_completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        kanonenv = _write_kanonenv_sources(
            workspace,
            marketplace_dir,
            sources=[
                ("source_alpha", f"file://{bare_alpha}"),
                ("source_bravo", f"file://{bare_bravo}"),
            ],
        )

        with (
            patch("kanon_cli.repo.repo_init", side_effect=_make_repo_init_with_linkfiles(marketplace_dir)),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.marketplace.shutil.which", return_value=claude_bin),
            patch("kanon_cli.core.marketplace.subprocess.run", return_value=mock_completed),
        ):
            install(kanonenv, lock_file_path=lock_path)

        installed_lock = read_lockfile(lock_path)
        assert "source_alpha" in {
            mp for s in installed_lock.sources if s.name == "source_alpha" for mp in s.registered_marketplaces
        }

        _write_kanonenv_sources(
            workspace,
            marketplace_dir,
            sources=[("source_bravo", f"file://{bare_bravo}")],
        )

        with (
            patch("kanon_cli.core.clean.uninstall_marketplace_plugins"),
            patch("kanon_cli.core.marketplace.shutil.which", return_value=claude_bin),
            patch("kanon_cli.core.marketplace.subprocess.run", return_value=mock_completed) as mock_run,
        ):
            clean(kanonenv, orphans=True)

        removed = _extract_marketplace_remove_names(mock_run.call_args_list)
        assert "source_alpha" in removed, (
            f"clean --orphans must unregister removed source A's marketplace 'source_alpha'; "
            f"recorded removes: {removed!r}"
        )
        assert "source_bravo" not in removed, (
            f"source B is still in .kanon; its marketplace must NOT be removed; recorded removes: {removed!r}"
        )
        for keep in _KEEP_SET_NAMES:
            assert keep not in removed, (
                f"Keep-set marketplace {keep!r} was never in any ledger and must never be removed; "
                f"recorded removes: {removed!r}"
            )
