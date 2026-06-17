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

import pytest

from tests.integration.test_add_core import (
    _create_manifest_repo_with_tags,
    _run_kanon,
)


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

        # Remove any catalog-source env var so the install is truly bare.
        env = dict(os.environ)
        env.pop("KANON_CATALOG_SOURCE", None)

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

        assert lock_data["schema_version"] == 4, (
            f"expected a schema-v4 lockfile, got schema_version={lock_data.get('schema_version')!r}.\n"
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
        env.pop("KANON_CATALOG_SOURCE", None)

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
        assert "'kanon install' does not accept a catalog source" in install_result.stderr, (
            f"kanon install --catalog-source did not emit the hermetic-install diagnostic on stderr.\n"
            f"  exit code: {install_result.returncode}\n"
            f"  stderr   : {install_result.stderr!r}"
        )
