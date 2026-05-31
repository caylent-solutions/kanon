"""Integration tests: bare `kanon install` after `kanon add` (DEFECT-001).

Asserts the canonical two-command workflow:

    kanon add <entry> --catalog-source <url>
    kanon install           # no --catalog-source flag, no env var

returns exit 0 and writes `.kanon.lock` whose `[catalog].source` matches
the URL originally passed to `kanon add`.

These tests are RED against unfixed code: `kanon install` exits 2 with
"install requires a catalog source" because the lockfile-absent path has no
CLI/env catalog source and no lockfile fallback available yet.

The tests use the synthetic-fixture helper `_create_manifest_repo_with_tags`
from `tests.integration.test_add_core` and inherit the autouse fixtures from
`tests/integration/conftest.py` (`_mock_resolve_ref_to_sha`,
`_mock_check_sha_reachable`, `_auto_create_manifest_on_walk`,
`_default_allow_insecure_remotes`).

Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
Section 4 E22 Failing test.
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
        """kanon install exits 0 after kanon add and writes .kanon.lock with [catalog].source.

        Asserts:
        1. exit code is 0 (not the current exit-2 / "install requires a catalog source").
        2. .kanon.lock exists on disk.
        3. lockfile [catalog].source equals the catalog-source URL passed to kanon add.
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

        recorded_source = lock_data.get("catalog", {}).get("source", "")
        assert recorded_source == catalog_source, (
            f"lockfile [catalog].source mismatch.\n"
            f"  Expected: {catalog_source!r}\n"
            f"  Got     : {recorded_source!r}\n"
            f"  Full lockfile: {lock_data!r}"
        )

    def test_explicit_flag_overrides_catalog_block(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--catalog-source on install overrides the [catalog] block written by kanon add.

        After `kanon add foo --catalog-source <add-url>`, running
        `kanon install --catalog-source <other-url>` should record <other-url>
        in the lockfile's [catalog].source, not the add-time URL.
        """
        bare = _create_manifest_repo_with_tags(
            tmp_path / "catalog",
            entry_names=["foo"],
            tags=["1.0.0"],
        )
        add_catalog_source = f"file://{bare}@main"

        # Build a second bare repo to use as the override catalog source.
        other_bare = _create_manifest_repo_with_tags(
            tmp_path / "other-catalog",
            entry_names=["foo"],
            tags=["1.0.0"],
        )
        override_catalog_source = f"file://{other_bare}@main"

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
            [sys.executable, "-m", "kanon_cli", "install", "--catalog-source", override_catalog_source],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(workspace),
        )

        assert install_result.returncode == 0, (
            f"Expected kanon install to exit 0 with explicit --catalog-source, "
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

        recorded_source = lock_data.get("catalog", {}).get("source", "")
        assert recorded_source == override_catalog_source, (
            f"lockfile [catalog].source should be the explicit flag value.\n"
            f"  Expected (override): {override_catalog_source!r}\n"
            f"  Got                : {recorded_source!r}\n"
            f"  Full lockfile      : {lock_data!r}"
        )
