"""Integration tests: bare `kanon install` after `kanon add` (DEFECT-001, hermetic install).

Asserts the canonical two-command workflow under the schema-v4 hermetic-install
model:

    kanon add <entry> --catalog-source <url>
    kanon install           # no --catalog-source flag, no env var

returns exit 0 and writes a schema-v4 `.kanon.lock` (no `[catalog]` block) for the
sources `kanon add` declared in `.kanon`.  `kanon install` is hermetic: it installs
exactly the sources declared in `.kanon` and pinned in `.kanon.lock` and never
resolves a remote catalog, so a `--catalog-source` flag reaching install is
rejected fail-fast (schema v4 / FR-7).

The tests use the synthetic-fixture helper `_create_manifest_repo_with_tags`
from `tests.integration.test_add_core` and inherit the autouse fixtures from
`tests/integration/conftest.py` (`_mock_resolve_ref_to_sha`,
`_mock_check_sha_reachable`, `_auto_create_manifest_on_walk`,
`_default_allow_insecure_remotes`).

Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
Section 4 E22 Failing test; schema-v4 hermetic install (FR-7).
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tomllib
from unittest.mock import patch

import pytest

from kanon_cli.core.install import install
from tests.integration.test_add_core import (
    _create_manifest_repo_with_tags,
    _create_marketplace_manifest_repo,
    _run_kanon,
)
from tests.integration.test_install_marketplace_registration import (
    _extract_marketplace_add_argvs,
    _make_repo_init_with_linkfiles,
)


_CLAUDE_MARKETPLACES_DIR_HEADER = "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces"


@pytest.mark.integration
class TestInstallAfterAdd:
    """Bare `kanon install` must succeed after `kanon add` without re-passing --catalog-source."""

    def test_install_succeeds_without_catalog_source_flag_after_add(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """kanon install exits 0 after kanon add and writes a schema-v4 .kanon.lock.

        Asserts:
        1. exit code is 0 (bare install succeeds after add).
        2. .kanon.lock exists on disk.
        3. the lockfile is schema v4 and carries NO [catalog] block (hermetic
           install records no catalog source).
        """
        bare = _create_manifest_repo_with_tags(
            tmp_path / "catalog",
            entry_names=["foo"],
            tags=["1.0.0"],
        )
        catalog_source = f"file://{bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        add_result = _run_kanon(
            [
                "add",
                "foo",
                "--catalog-source",
                catalog_source,
            ],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (expected 0, got {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\nstderr: {add_result.stderr!r}"
        )

        env = dict(os.environ)
        env.pop("KANON_CATALOG_SOURCES", None)

        install_result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(workspace),
        )

        assert install_result.returncode == 0, (
            f"Expected kanon install to exit 0 after kanon add, "
            f"got exit {install_result.returncode}.\n"
            f"stdout: {install_result.stdout!r}\nstderr: {install_result.stderr!r}"
        )

        lock_path = workspace / ".kanon.lock"
        assert lock_path.exists(), (
            f".kanon.lock was not written at {lock_path}. "
            f"kanon install stdout: {install_result.stdout!r} "
            f"stderr: {install_result.stderr!r}"
        )

        with lock_path.open("rb") as fh:
            lock_data = tomllib.load(fh)

        assert lock_data["schema_version"] == 5, (
            f"expected a schema-v5 lockfile, got schema_version={lock_data.get('schema_version')!r}.\n"
            f"  Full lockfile: {lock_data!r}"
        )
        assert "catalog" not in lock_data, (
            f"schema v4 removed the [catalog] block; the hermetic install must not record a catalog source.\n"
            f"  Full lockfile: {lock_data!r}"
        )

    def test_install_rejects_catalog_source_flag(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`kanon install --catalog-source <url>` is rejected fail-fast (hermetic install).

        Schema v4 (FR-7) made `kanon install` hermetic: it installs exactly the
        sources declared in `.kanon` and pinned in `.kanon.lock` and never resolves
        a remote catalog.  Supplying `--catalog-source` to install is therefore an
        operator error rejected with a non-zero exit and the hermetic-install
        diagnostic on stderr, not silently honoured.
        """
        bare = _create_manifest_repo_with_tags(
            tmp_path / "catalog",
            entry_names=["foo"],
            tags=["1.0.0"],
        )
        add_catalog_source = f"file://{bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        add_result = _run_kanon(
            [
                "add",
                "foo",
                "--catalog-source",
                add_catalog_source,
            ],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (expected 0, got {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\nstderr: {add_result.stderr!r}"
        )

        env = dict(os.environ)
        env.pop("KANON_CATALOG_SOURCES", None)

        install_result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install", "--catalog-source", add_catalog_source],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(workspace),
        )

        assert install_result.returncode != 0, (
            f"Expected kanon install --catalog-source to exit non-zero (hermetic install), "
            f"got exit {install_result.returncode}.\n"
            f"stdout: {install_result.stdout!r}\nstderr: {install_result.stderr!r}"
        )

        assert "--catalog-source" in install_result.stderr and "unrecognized arguments" in install_result.stderr, (
            f"kanon install --catalog-source must be rejected as an unrecognized argument.\n"
            f"  exit code: {install_result.returncode}\n"
            f"  stderr   : {install_result.stderr!r}"
        )


@pytest.mark.integration
class TestMarketplaceInstallAfterAdd:
    """`kanon add <claude-marketplace>` then `kanon install` works with no manual header (Feature A)."""

    def test_marketplace_add_then_install_succeeds_with_one_header(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """add of a marketplace entry writes one header; the subsequent install consumes it and exits cleanly.

        The end-to-end gap the auto-managed header closes: before the fix a bare
        ``kanon add <marketplace> ; kanon install`` failed because ``add`` wrote no
        ``CLAUDE_MARKETPLACES_DIR`` header and ``install`` requires it.  Here ``add``
        runs as a real subprocess (writing the literal ``${HOME}`` header exactly
        once) and ``install`` runs in-process with the marketplace registration
        mocks (so it never shells out to a real ``claude`` binary).  ``HOME`` is
        redirected to a tmp dir so the expanded marketplace directory stays
        hermetic.
        """
        bare = _create_marketplace_manifest_repo(
            tmp_path / "catalog",
            entry_name="mp-entry",
            tags=["1.0.0"],
        )
        catalog_source = f"file://{bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        add_result = _run_kanon(
            [
                "add",
                "mp-entry",
                "--catalog-source",
                catalog_source,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (expected 0, got {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\nstderr: {add_result.stderr!r}"
        )

        content_after_add = kanon_file.read_text()
        assert content_after_add.count(_CLAUDE_MARKETPLACES_DIR_HEADER) == 1, (
            f"kanon add must auto-write the marketplace header exactly once; got:\n{content_after_add}"
        )
        assert "KANON_SOURCE_mp_entry_MARKETPLACE=true" in content_after_add
        assert not (workspace / ".kanon-data").exists(), (
            "kanon add must not create a .kanon-data lock dir in the project CWD"
        )

        tmp_home = tmp_path / "home"
        tmp_home.mkdir()
        monkeypatch.setenv("HOME", str(tmp_home))
        marketplace_dir = tmp_home / ".claude-marketplaces"

        claude_bin = "/usr/bin/claude"
        mock_completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch(
                "kanon_cli.repo.repo_init",
                side_effect=_make_repo_init_with_linkfiles(marketplace_dir),
            ),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch(
                "kanon_cli.core.marketplace.shutil.which",
                return_value=claude_bin,
            ),
            patch(
                "kanon_cli.core.marketplace.subprocess.run",
                return_value=mock_completed,
            ) as mock_run,
        ):
            install(
                kanon_file,
                lock_file_path=workspace / ".kanon.lock",
            )

        recorded_add_argvs = _extract_marketplace_add_argvs(mock_run.call_args_list)
        expected = (claude_bin, "plugin", "marketplace", "add", str(marketplace_dir / "mp-entry"))
        assert expected in recorded_add_argvs, (
            f"Expected the marketplace entry to register via {expected!r} after add->install; "
            f"recorded calls: {recorded_add_argvs}"
        )

        assert (workspace / ".kanon.lock").exists(), "install must write .kanon.lock"
        content_after_install = kanon_file.read_text()
        assert content_after_install.count(_CLAUDE_MARKETPLACES_DIR_HEADER) == 1, (
            f"install must leave exactly one marketplace header; got:\n{content_after_install}"
        )
