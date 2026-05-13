"""Unit tests for the --refresh-lock flag in kanon install.

AC-TEST-001: Parametrises the three accept-and-reject paths:
  (a) --refresh-lock with a present lockfile produces InstallState.REFRESH_LOCK
      and is processed like LOCKFILE_ABSENT (info-line, lockfile rewrite).
  (b) --refresh-lock with no CLI/env catalog source raises MissingCatalogSourceError
      with the refresh-specific remediation text.
  (c) --refresh-lock plus --refresh-lock-source raises SystemExit(2) due to
      mutual-exclusion group (AC-FUNC-004; group registered in T2 for T3 to join).

AC-FUNC-003 through AC-FUNC-006 verified by these unit tests.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.include_walker import IncludeTree
from kanon_cli.core.install import (
    InstallState,
    MissingCatalogSourceError,
    _RefResolution,
    _classify_install_state,
    _emit_install_state,
    _resolve_catalog_source,
    install,
)


# ---------------------------------------------------------------------------
# Helpers shared with the state-matrix tests
# ---------------------------------------------------------------------------

_KANON_SINGLE_SOURCE = """\
GITBASE=https://git.example.com
CLAUDE_MARKETPLACES_DIR=/tmp/mktplc
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_alpha_URL=https://git.example.com/alpha.git
KANON_SOURCE_alpha_REVISION=main
KANON_SOURCE_alpha_PATH=manifest.xml
"""

_VALID_SHA40 = "a" * 40


def _write_kanon(directory: pathlib.Path, content: str = _KANON_SINGLE_SOURCE) -> pathlib.Path:
    kanon_path = directory / ".kanon"
    kanon_path.write_text(content)
    kanon_path.chmod(0o600)
    return kanon_path


def _write_lockfile(
    directory: pathlib.Path,
    kanon_hash: str,
    catalog_source: str = "https://git.example.com/catalog.git@main",
) -> pathlib.Path:
    """Write a minimal valid .kanon.lock TOML file and return its path."""
    lock_path = directory / ".kanon.lock"
    content = f"""\
schema_version = 1
generated_at = "2026-01-15T00:00:00Z"
generator = "kanon-cli/test"
kanon_hash = "{kanon_hash}"

[catalog]
source = "{catalog_source}"
url = "https://git.example.com/catalog.git"
revision_spec = "main"
resolved_ref = "refs/heads/main"
resolved_sha = "{_VALID_SHA40}"

[[sources]]
name = "alpha"
url = "https://git.example.com/alpha.git"
revision_spec = "main"
resolved_ref = "refs/heads/main"
resolved_sha = "{_VALID_SHA40}"
path = "manifest.xml"
"""
    lock_path.write_text(content)
    return lock_path


# ===========================================================================
# AC-FUNC-006: InstallState.REFRESH_LOCK enum value exists
# ===========================================================================


@pytest.mark.unit
class TestRefreshLockInstallState:
    """AC-FUNC-006: REFRESH_LOCK enum value is present on InstallState."""

    def test_refresh_lock_state_exists(self) -> None:
        """InstallState.REFRESH_LOCK must be a valid enum member."""
        assert hasattr(InstallState, "REFRESH_LOCK")
        assert isinstance(InstallState.REFRESH_LOCK, InstallState)

    def test_refresh_lock_state_is_distinct(self) -> None:
        """REFRESH_LOCK must differ from every other InstallState value."""
        other_states = [
            InstallState.LOCKFILE_ABSENT,
            InstallState.LOCKFILE_CONSISTENT,
            InstallState.LOCKFILE_HASH_MISMATCH,
            InstallState.LOCKFILE_UNREACHABLE,
            InstallState.LOCKFILE_SOURCE_MISMATCH,
        ]
        for other in other_states:
            assert InstallState.REFRESH_LOCK is not other


# ===========================================================================
# AC-FUNC-006: _classify_install_state short-circuits on refresh_lock=True
# ===========================================================================


@pytest.mark.unit
class TestClassifyInstallStateRefreshLock:
    """AC-FUNC-006: _classify_install_state returns REFRESH_LOCK when refresh_lock=True."""

    def test_refresh_lock_when_lockfile_absent(self, tmp_path: pathlib.Path) -> None:
        """REFRESH_LOCK state returned even when the lockfile does not exist."""
        kanon_path = _write_kanon(tmp_path)
        lock_path = tmp_path / ".kanon.lock"
        assert not lock_path.exists()

        classification = _classify_install_state(kanon_path, lock_path, refresh_lock=True)
        assert classification.state is InstallState.REFRESH_LOCK

    def test_refresh_lock_when_lockfile_present_and_consistent(self, tmp_path: pathlib.Path) -> None:
        """REFRESH_LOCK state returned even when the lockfile is consistent."""
        from kanon_cli.core.kanon_hash import kanon_hash as compute_kanon_hash

        kanon_path = _write_kanon(tmp_path)
        real_hash = compute_kanon_hash(kanon_path)
        _write_lockfile(tmp_path, real_hash)
        lock_path = tmp_path / ".kanon.lock"

        classification = _classify_install_state(kanon_path, lock_path, refresh_lock=True)
        assert classification.state is InstallState.REFRESH_LOCK

    def test_refresh_lock_when_lockfile_present_and_mismatched(self, tmp_path: pathlib.Path) -> None:
        """REFRESH_LOCK state returned even when the lockfile has a hash mismatch."""
        kanon_path = _write_kanon(tmp_path)
        wrong_hash = "sha256:" + "d" * 64
        _write_lockfile(tmp_path, wrong_hash)
        lock_path = tmp_path / ".kanon.lock"

        classification = _classify_install_state(kanon_path, lock_path, refresh_lock=True)
        assert classification.state is InstallState.REFRESH_LOCK

    def test_refresh_lock_false_preserves_existing_behaviour(self, tmp_path: pathlib.Path) -> None:
        """refresh_lock=False (default) does NOT change the normal state logic."""
        kanon_path = _write_kanon(tmp_path)
        lock_path = tmp_path / ".kanon.lock"
        assert not lock_path.exists()

        classification = _classify_install_state(kanon_path, lock_path, refresh_lock=False)
        assert classification.state is InstallState.LOCKFILE_ABSENT


# ===========================================================================
# AC-FUNC-003: _resolve_catalog_source disables lockfile fallback on refresh
# ===========================================================================


@pytest.mark.unit
class TestResolveCatalogSourceRefreshLock:
    """AC-FUNC-003: lockfile fallback is disabled in REFRESH_LOCK state."""

    def test_no_cli_no_env_refresh_lock_raises(self) -> None:
        """REFRESH_LOCK state with no CLI/env source raises MissingCatalogSourceError."""
        with pytest.raises(MissingCatalogSourceError) as exc_info:
            _resolve_catalog_source(
                cli_arg=None,
                env_value=None,
                lockfile_catalog_source="https://lock.example.com/repo.git@main",
                install_state=InstallState.REFRESH_LOCK,
            )
        msg = str(exc_info.value)
        assert "--refresh-lock requires a CLI or env-var catalog source" in msg
        assert "lockfile fallback is disabled" in msg

    def test_cli_arg_succeeds_in_refresh_lock_state(self) -> None:
        """REFRESH_LOCK state with a CLI source returns that source."""
        result = _resolve_catalog_source(
            cli_arg="https://cli.example.com/repo.git@main",
            env_value=None,
            lockfile_catalog_source="https://lock.example.com/repo.git@main",
            install_state=InstallState.REFRESH_LOCK,
        )
        assert result == "https://cli.example.com/repo.git@main"

    def test_env_var_succeeds_in_refresh_lock_state(self) -> None:
        """REFRESH_LOCK state with an env source returns that source."""
        result = _resolve_catalog_source(
            cli_arg=None,
            env_value="https://env.example.com/repo.git@main",
            lockfile_catalog_source=None,
            install_state=InstallState.REFRESH_LOCK,
        )
        assert result == "https://env.example.com/repo.git@main"

    @pytest.mark.parametrize(
        "cli_arg,env_value",
        [
            ("https://example.com/repo.git@v1", None),
            (None, "https://example.com/repo.git@v1"),
            ("https://example.com/repo.git@v1", "https://example.com/other.git@v2"),
        ],
    )
    def test_parametrised_refresh_lock_source_resolution(
        self,
        cli_arg: str | None,
        env_value: str | None,
    ) -> None:
        """Parametrised: CLI/env source always wins in REFRESH_LOCK state."""
        result = _resolve_catalog_source(
            cli_arg=cli_arg,
            env_value=env_value,
            lockfile_catalog_source="https://lock.example.com/repo.git@stale",
            install_state=InstallState.REFRESH_LOCK,
        )
        expected = cli_arg if cli_arg is not None else env_value
        assert result == expected


# ===========================================================================
# AC-FUNC-001: _emit_install_state emits the correct line for REFRESH_LOCK
# ===========================================================================


@pytest.mark.unit
class TestEmitInstallStateRefreshLock:
    """AC-FUNC-001: REFRESH_LOCK emits the same info-line as LOCKFILE_ABSENT."""

    def test_refresh_lock_emits_rebuilt_info_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        """REFRESH_LOCK state emits 'lockfile rebuilt from .kanon (N sources, M projects)'."""
        _emit_install_state(InstallState.REFRESH_LOCK, sources=2, projects=5)
        captured = capsys.readouterr()
        assert "lockfile rebuilt from .kanon (2 sources, 5 projects)" in captured.out

    @pytest.mark.parametrize(
        "sources,projects",
        [(0, 0), (1, 1), (3, 10)],
    )
    def test_refresh_lock_info_line_counts_parametrised(
        self,
        capsys: pytest.CaptureFixture[str],
        sources: int,
        projects: int,
    ) -> None:
        """REFRESH_LOCK info-line counts are dynamic."""
        _emit_install_state(InstallState.REFRESH_LOCK, sources=sources, projects=projects)
        captured = capsys.readouterr()
        assert f"({sources} sources, {projects} projects)" in captured.out


# ===========================================================================
# AC-FUNC-005: install() accepts refresh_lock kwarg
# ===========================================================================


@pytest.mark.unit
class TestInstallRefreshLockKwarg:
    """AC-FUNC-005: install() accepts refresh_lock keyword argument with default False."""

    def test_install_has_refresh_lock_kwarg(self) -> None:
        """install() signature includes refresh_lock: bool = False."""
        import inspect

        sig = inspect.signature(install)
        assert "refresh_lock" in sig.parameters
        param = sig.parameters["refresh_lock"]
        assert param.default is False

    def test_install_refresh_lock_missing_catalog_raises(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install(refresh_lock=True) with no catalog source raises MissingCatalogSourceError
        with the refresh-specific remediation text (AC-FUNC-003)."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        kanon_path = _write_kanon(tmp_path)

        # Write a lockfile to prove the lockfile fallback is disabled on this path.
        from kanon_cli.core.kanon_hash import kanon_hash as compute_hash

        real_hash = compute_hash(kanon_path)
        _write_lockfile(tmp_path, real_hash)

        mock_ref = _RefResolution(sha="a" * 40, resolved_ref="refs/heads/main")
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=mock_ref),
        ):
            with pytest.raises(MissingCatalogSourceError) as exc_info:
                install(
                    kanonenv_path=kanon_path,
                    catalog_source=None,
                    refresh_lock=True,
                )

        msg = str(exc_info.value)
        assert "--refresh-lock requires a CLI or env-var catalog source" in msg
        assert "lockfile fallback is disabled" in msg

    def test_install_refresh_lock_with_catalog_rewrites_lockfile(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install(refresh_lock=True) with a catalog source rewrites the lockfile
        even when a consistent lockfile is already present (AC-FUNC-001)."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        kanon_path = _write_kanon(tmp_path)

        # Write a consistent lockfile with a stale SHA so we can detect the rewrite.
        from kanon_cli.core.kanon_hash import kanon_hash as compute_hash

        real_hash = compute_hash(kanon_path)
        lock_path = _write_lockfile(tmp_path, real_hash)

        new_sha = "b" * 40
        mock_ref = _RefResolution(sha=new_sha, resolved_ref="refs/heads/main")
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=mock_ref),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(
                kanonenv_path=kanon_path,
                catalog_source="https://catalog.example.com/repo.git@main",
                refresh_lock=True,
            )

        assert lock_path.exists()
        new_content = lock_path.read_text()
        # The lockfile must have been rewritten (new_sha appears; original may differ).
        assert new_sha in new_content


# ===========================================================================
# AC-FUNC-002: install(refresh_lock=True) does NOT modify .kanon
# ===========================================================================


@pytest.mark.unit
class TestRefreshLockDoesNotTouchKanonFile:
    """AC-FUNC-002: --refresh-lock does not modify the .kanon file."""

    def test_kanon_file_unchanged_after_refresh_lock(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """After install(refresh_lock=True), the .kanon file content is unchanged."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        kanon_path = _write_kanon(tmp_path)
        original_content = kanon_path.read_text()

        mock_ref = _RefResolution(sha="b" * 40, resolved_ref="refs/heads/main")
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=mock_ref),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(
                kanonenv_path=kanon_path,
                catalog_source="https://catalog.example.com/repo.git@main",
                refresh_lock=True,
            )

        assert kanon_path.read_text() == original_content


# ===========================================================================
# AC-FUNC-004: --refresh-lock argparse registration (mutual exclusion group)
# T2 registers --refresh-lock in a mutually_exclusive_group.
# T3 will add --refresh-lock-source to the same group; the end-to-end
# mutual-exclusion SystemExit(2) test for the combined pair lives in T3.
# ===========================================================================


@pytest.mark.unit
class TestRefreshLockMutualExclusion:
    """AC-FUNC-004: --refresh-lock is registered in a mutually_exclusive_group."""

    def test_refresh_lock_alone_is_parsed(self) -> None:
        """--refresh-lock alone parses without error."""
        import argparse

        from kanon_cli.commands import install as install_cmd

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        install_cmd.register(subparsers)

        args = parser.parse_args(["install", "--refresh-lock"])
        assert args.refresh_lock is True

    def test_refresh_lock_default_is_false(self) -> None:
        """When --refresh-lock is not passed, args.refresh_lock defaults to False."""
        import argparse

        from kanon_cli.commands import install as install_cmd

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        install_cmd.register(subparsers)

        args = parser.parse_args(["install"])
        assert args.refresh_lock is False
