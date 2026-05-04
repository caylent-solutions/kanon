"""RP-wrap-01..04: `kanon repo` wrapper flag scenarios.

Automates §26 of `docs/integration-testing.md`.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios._rp_helpers import build_rp_ro_manifest
from tests.scenarios.conftest import run_kanon


@pytest.mark.scenario
class TestRPWrap:
    """RP-wrap-01..04: `kanon repo` wrapper flags and environment variables."""

    def test_rp_wrap_01_repo_dir_flag(self, tmp_path: pathlib.Path) -> None:
        """RP-wrap-01: `--repo-dir=<custom>` creates `.repo` at the given path."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        custom_repo_dir = tmp_path / "custom-repo"
        ws = tmp_path / "ws"
        ws.mkdir()

        result = run_kanon(
            "repo",
            f"--repo-dir={custom_repo_dir}",
            "init",
            "-u",
            manifest_bare.as_uri(),
            "-b",
            "main",
            "-m",
            "repo-specs/packages.xml",
            cwd=ws,
        )

        assert result.returncode == 0, (
            f"repo --repo-dir init exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert custom_repo_dir.exists(), f"Expected custom repo dir {custom_repo_dir} to exist after init"

    def test_rp_wrap_02_kanon_repo_dir_env(self, tmp_path: pathlib.Path) -> None:
        """RP-wrap-02: env `KANON_REPO_DIR=<custom>` creates `.repo` at the env-specified path."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        env_repo_dir = tmp_path / "env-repo"
        ws = tmp_path / "ws"
        ws.mkdir()

        result = run_kanon(
            "repo",
            "init",
            "-u",
            manifest_bare.as_uri(),
            "-b",
            "main",
            "-m",
            "repo-specs/packages.xml",
            cwd=ws,
            extra_env={"KANON_REPO_DIR": str(env_repo_dir)},
        )

        assert result.returncode == 0, (
            f"repo init with KANON_REPO_DIR exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert env_repo_dir.exists(), f"Expected KANON_REPO_DIR path {env_repo_dir} to exist after init"

    def test_rp_wrap_03_repo_dir_flag_overrides_env(self, tmp_path: pathlib.Path) -> None:
        """RP-wrap-03: `--repo-dir` flag wins over `KANON_REPO_DIR` env var."""
        manifest_bare = build_rp_ro_manifest(tmp_path / "fixtures")
        env_dir = tmp_path / "env-A"
        flag_dir = tmp_path / "flag-B"
        ws = tmp_path / "ws"
        ws.mkdir()

        result = run_kanon(
            "repo",
            f"--repo-dir={flag_dir}",
            "init",
            "-u",
            manifest_bare.as_uri(),
            "-b",
            "main",
            "-m",
            "repo-specs/packages.xml",
            cwd=ws,
            extra_env={"KANON_REPO_DIR": str(env_dir)},
        )

        assert result.returncode == 0, (
            f"repo --repo-dir (override env) exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert flag_dir.exists(), f"Expected flag-specified dir {flag_dir} to exist"
        assert not env_dir.exists(), f"Expected env-specified dir {env_dir} NOT to exist (flag should have won)"

    def test_rp_wrap_04_selfupdate_disabled(self, tmp_path: pathlib.Path) -> None:
        """RP-wrap-04: `kanon repo selfupdate` emits 'selfupdate is not available' on stderr and exits 1."""
        result = run_kanon("repo", "selfupdate", cwd=tmp_path)

        assert result.returncode == 1, (
            f"repo selfupdate should exit 1 but exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "selfupdate is not available" in result.stderr, (
            f"Expected 'selfupdate is not available' in stderr: {result.stderr!r}"
        )
        assert result.stdout == "", f"Expected empty stdout for repo selfupdate but got: {result.stdout!r}"
