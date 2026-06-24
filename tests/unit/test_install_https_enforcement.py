"""Unit tests for HTTPS enforcement wiring in the install module.

Tests that _run_install calls _enforce_remote_url_policy with the correct
arguments derived from the KANON_ALLOW_INSECURE_REMOTES environment variable.

AC-TEST-001 coverage: wiring test asserting install calls the policy enforcer
with the correct args from env.
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.core.install import InstallError, _run_install
from kanon_cli.core.remote_url import InsecureRemoteUrlError


def _write_kanon(directory: pathlib.Path, url: str, scheme: str = "http") -> pathlib.Path:
    """Write a minimal .kanon file pointing at the given URL.

    Args:
        directory: Directory in which to create the .kanon file.
        url: The source URL to write.
        scheme: Not used -- kept for readability at call sites.

    Returns:
        Absolute path to the written .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_mysource_URL={url}\n"
        f"KANON_SOURCE_mysource_REF=main\n"
        f"KANON_SOURCE_mysource_PATH=repo-specs/manifest.xml\n"
        f"KANON_SOURCE_mysource_NAME=mysource\n"
        f"KANON_SOURCE_mysource_GITBASE=https://example.com\n"
    )
    return kanonenv.resolve()


@pytest.mark.unit
class TestInstallEnforcesHttpsPolicy:
    """Tests that _run_install calls _enforce_remote_url_policy for each source URL."""

    def test_policy_enforcer_called_on_absent_lockfile_path(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_enforce_remote_url_policy is called for each source URL on the absent-lockfile path."""
        monkeypatch.delenv("KANON_ALLOW_INSECURE_REMOTES", raising=False)
        kanonenv = _write_kanon(tmp_path, "https://example.com/repo.git")
        lockfile_path = tmp_path / ".kanon.lock"

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha") as mock_resolve,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            patch("kanon_cli.core.install._walk_includes") as mock_walk,
            patch("kanon_cli.core.install._include_tree_to_entries", return_value=[]),
            patch("kanon_cli.core.install.aggregate_symlinks", return_value={}),
            patch("kanon_cli.core.install.update_gitignore"),
            patch("kanon_cli.core.install._emit_install_state"),
            patch("kanon_cli.core.install._enforce_remote_url_policy") as mock_policy,
        ):
            from kanon_cli.core.install import _RefResolution

            mock_resolve.return_value = _RefResolution(sha="a" * 40, resolved_ref="refs/heads/main")
            mock_walk.return_value = MagicMock(includes=[])

            _run_install(
                kanonenv_path=kanonenv,
                lockfile_path=lockfile_path,
            )

        mock_policy.assert_called()

    def test_policy_enforcer_called_with_allow_insecure_false_by_default(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When KANON_ALLOW_INSECURE_REMOTES is unset, allow_insecure=False is passed."""
        monkeypatch.delenv("KANON_ALLOW_INSECURE_REMOTES", raising=False)
        kanonenv = _write_kanon(tmp_path, "https://example.com/repo.git")
        lockfile_path = tmp_path / ".kanon.lock"

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha") as mock_resolve,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            patch("kanon_cli.core.install._walk_includes") as mock_walk,
            patch("kanon_cli.core.install._include_tree_to_entries", return_value=[]),
            patch("kanon_cli.core.install.aggregate_symlinks", return_value={}),
            patch("kanon_cli.core.install.update_gitignore"),
            patch("kanon_cli.core.install._emit_install_state"),
            patch("kanon_cli.core.install._enforce_remote_url_policy") as mock_policy,
        ):
            from kanon_cli.core.install import _RefResolution

            mock_resolve.return_value = _RefResolution(sha="a" * 40, resolved_ref="refs/heads/main")
            mock_walk.return_value = MagicMock(includes=[])

            _run_install(
                kanonenv_path=kanonenv,
                lockfile_path=lockfile_path,
            )

        for c in mock_policy.call_args_list:
            assert c.kwargs.get("allow_insecure") is False or (len(c.args) >= 2 and c.args[1] is False)

    def test_policy_enforcer_called_with_allow_insecure_true_when_env_set(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When KANON_ALLOW_INSECURE_REMOTES=1, allow_insecure=True is passed."""
        monkeypatch.setenv("KANON_ALLOW_INSECURE_REMOTES", "1")
        kanonenv = _write_kanon(tmp_path, "https://example.com/repo.git")
        lockfile_path = tmp_path / ".kanon.lock"

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha") as mock_resolve,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            patch("kanon_cli.core.install._walk_includes") as mock_walk,
            patch("kanon_cli.core.install._include_tree_to_entries", return_value=[]),
            patch("kanon_cli.core.install.aggregate_symlinks", return_value={}),
            patch("kanon_cli.core.install.update_gitignore"),
            patch("kanon_cli.core.install._emit_install_state"),
            patch("kanon_cli.core.install._enforce_remote_url_policy") as mock_policy,
        ):
            from kanon_cli.core.install import _RefResolution

            mock_resolve.return_value = _RefResolution(sha="a" * 40, resolved_ref="refs/heads/main")
            mock_walk.return_value = MagicMock(includes=[])

            _run_install(
                kanonenv_path=kanonenv,
                lockfile_path=lockfile_path,
            )

        any_true = any(
            c.kwargs.get("allow_insecure") is True or (len(c.args) >= 2 and c.args[1] is True)
            for c in mock_policy.call_args_list
        )
        assert any_true, "Expected at least one call with allow_insecure=True"

    def test_http_url_raises_insecure_error_by_default(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When source URL is HTTP and env var unset, InsecureRemoteUrlError is raised."""
        monkeypatch.delenv("KANON_ALLOW_INSECURE_REMOTES", raising=False)
        kanonenv = _write_kanon(tmp_path, "http://example.com/repo.git")
        lockfile_path = tmp_path / ".kanon.lock"

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha") as mock_resolve,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            patch("kanon_cli.core.install._walk_includes") as mock_walk,
        ):
            from kanon_cli.core.install import _RefResolution

            mock_resolve.return_value = _RefResolution(sha="a" * 40, resolved_ref="refs/heads/main")
            mock_walk.return_value = MagicMock(includes=[])

            with pytest.raises(InsecureRemoteUrlError):
                _run_install(
                    kanonenv_path=kanonenv,
                    lockfile_path=lockfile_path,
                )

    def test_http_url_allowed_when_env_var_set_to_one(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When source URL is HTTP and KANON_ALLOW_INSECURE_REMOTES=1, no error is raised."""
        monkeypatch.setenv("KANON_ALLOW_INSECURE_REMOTES", "1")
        kanonenv = _write_kanon(tmp_path, "http://example.com/repo.git")
        lockfile_path = tmp_path / ".kanon.lock"

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha") as mock_resolve,
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            patch("kanon_cli.core.install._walk_includes") as mock_walk,
            patch("kanon_cli.core.install._include_tree_to_entries", return_value=[]),
            patch("kanon_cli.core.install.aggregate_symlinks", return_value={}),
            patch("kanon_cli.core.install.update_gitignore"),
            patch("kanon_cli.core.install._emit_install_state"),
        ):
            from kanon_cli.core.install import _RefResolution

            mock_resolve.return_value = _RefResolution(sha="a" * 40, resolved_ref="refs/heads/main")
            mock_walk.return_value = MagicMock(includes=[])

            _run_install(
                kanonenv_path=kanonenv,
                lockfile_path=lockfile_path,
            )


@pytest.mark.unit
class TestLockfileConsistentMissingSourceRaisesInstallError:
    """Under LOCKFILE_CONSISTENT state, a source absent from the lockfile is a hard error."""

    def test_source_missing_from_lockfile_raises_install_error(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If a .kanon source has no lockfile entry under LOCKFILE_CONSISTENT, InstallError is raised.

        This guards the kanon_hash consistency invariant: if the hash matched but a source
        is absent from the lockfile, something has corrupted the lockfile. A hard error is
        preferable to silently falling back to the .kanon URL.
        """
        monkeypatch.delenv("KANON_ALLOW_INSECURE_REMOTES", raising=False)

        kanonenv = _write_kanon(tmp_path, "https://example.com/repo.git")
        lockfile_path = tmp_path / ".kanon.lock"

        from kanon_cli.core.install import _kanon_hash
        from kanon_cli.core.lockfile import (
            CURRENT_SCHEMA_VERSION,
            Lockfile,
            write_lockfile,
        )

        kanon_hash_val = _kanon_hash(kanonenv)
        lf = Lockfile(
            schema_version=CURRENT_SCHEMA_VERSION,
            generated_at="2026-01-01T00:00:00Z",
            generator="kanon-cli/test",
            kanon_hash=kanon_hash_val,
            sources=[],
        )
        write_lockfile(lf, lockfile_path)

        with pytest.raises(InstallError, match="BUG: source 'mysource' not found in lockfile"):
            _run_install(
                kanonenv_path=kanonenv,
                lockfile_path=lockfile_path,
            )
