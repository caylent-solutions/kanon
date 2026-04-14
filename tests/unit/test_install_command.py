"""Tests for the install command handler."""

import argparse
import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestCheckPipx:
    def test_pipx_missing_exits(self) -> None:
        from kanon_cli.commands.install import _check_pipx

        with patch("kanon_cli.commands.install.shutil.which", return_value=None):
            with pytest.raises(SystemExit):
                _check_pipx()

    def test_pipx_present_ok(self) -> None:
        from kanon_cli.commands.install import _check_pipx

        with patch("kanon_cli.commands.install.shutil.which", return_value="/usr/bin/pipx"):
            _check_pipx()


@pytest.mark.unit
class TestInstallRepoToolFromGit:
    def test_success(self) -> None:
        from kanon_cli.commands.install import _install_repo_tool_from_git

        with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            _install_repo_tool_from_git("https://example.com/repo.git", "v2.0.0")
            cmd = mock_run.call_args[0][0]
            assert "pipx" in cmd
            assert "--force" in cmd
            assert "git+https://example.com/repo.git@v2.0.0" in cmd

    def test_failure_exits(self) -> None:
        from kanon_cli.commands.install import _install_repo_tool_from_git

        with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            with pytest.raises(SystemExit):
                _install_repo_tool_from_git("https://example.com/repo.git", "v2.0.0")


@pytest.mark.unit
class TestIsRepoToolInstalled:
    def test_installed_returns_true(self) -> None:
        from kanon_cli.commands.install import _is_repo_tool_installed

        pipx_json = json.dumps({"venvs": {"rpm-git-repo": {}}})
        with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=pipx_json)
            assert _is_repo_tool_installed() is True

    def test_not_installed_returns_false(self) -> None:
        from kanon_cli.commands.install import _is_repo_tool_installed

        pipx_json = json.dumps({"venvs": {"some-other-package": {}}})
        with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=pipx_json)
            assert _is_repo_tool_installed() is False

    def test_empty_venvs_returns_false(self) -> None:
        from kanon_cli.commands.install import _is_repo_tool_installed

        pipx_json = json.dumps({"venvs": {}})
        with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=pipx_json)
            assert _is_repo_tool_installed() is False

    def test_pipx_failure_exits(self) -> None:
        from kanon_cli.commands.install import _is_repo_tool_installed

        with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="err")
            with pytest.raises(SystemExit):
                _is_repo_tool_installed()

    def test_invalid_json_exits(self) -> None:
        from kanon_cli.commands.install import _is_repo_tool_installed

        with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="not json")
            with pytest.raises(SystemExit):
                _is_repo_tool_installed()

    def test_missing_venvs_key_exits(self) -> None:
        from kanon_cli.commands.install import _is_repo_tool_installed

        pipx_json = json.dumps({"unexpected": "structure"})
        with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=pipx_json)
            with pytest.raises(SystemExit):
                _is_repo_tool_installed()


@pytest.mark.unit
class TestEnsureRepoToolFromPypi:
    def test_already_installed_calls_pipx_upgrade(self) -> None:
        from kanon_cli.commands.install import _ensure_repo_tool_from_pypi

        with patch("kanon_cli.commands.install._is_repo_tool_installed", return_value=True):
            with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                _ensure_repo_tool_from_pypi()
                cmd = mock_run.call_args[0][0]
                assert "pipx" in cmd
                assert "upgrade" in cmd
                assert "rpm-git-repo" in cmd

    def test_already_installed_upgrade_at_latest(self) -> None:
        from kanon_cli.commands.install import _ensure_repo_tool_from_pypi

        with patch("kanon_cli.commands.install._is_repo_tool_installed", return_value=True):
            with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stderr="already at latest")
                _ensure_repo_tool_from_pypi()
                cmd = mock_run.call_args[0][0]
                assert "upgrade" in cmd

    def test_already_installed_does_not_call_install(self) -> None:
        from kanon_cli.commands.install import _ensure_repo_tool_from_pypi

        with patch("kanon_cli.commands.install._is_repo_tool_installed", return_value=True):
            with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                _ensure_repo_tool_from_pypi()
                assert mock_run.call_count == 1
                cmd = mock_run.call_args[0][0]
                assert "install" not in cmd

    def test_not_installed_calls_pipx_install(self) -> None:
        from kanon_cli.commands.install import _ensure_repo_tool_from_pypi

        with patch("kanon_cli.commands.install._is_repo_tool_installed", return_value=False):
            with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                _ensure_repo_tool_from_pypi()
                cmd = mock_run.call_args[0][0]
                assert "pipx" in cmd
                assert "install" in cmd
                assert "rpm-git-repo" in cmd
                assert "--force" not in cmd

    def test_install_failure_exits(self) -> None:
        from kanon_cli.commands.install import _ensure_repo_tool_from_pypi

        with patch("kanon_cli.commands.install._is_repo_tool_installed", return_value=False):
            with patch("kanon_cli.commands.install.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stderr="error")
                with pytest.raises(SystemExit):
                    _ensure_repo_tool_from_pypi()


@pytest.mark.unit
class TestRunPartialConfig:
    def test_repo_url_without_rev_exits(self, tmp_path) -> None:
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "REPO_URL=https://example.com/repo.git\n"
            "GITBASE=https://example.com/\n"
            "KANON_SOURCE_test_URL=https://example.com/manifest.git\n"
            "KANON_SOURCE_test_REVISION=main\n"
            "KANON_SOURCE_test_PATH=repo-specs/test.xml\n"
        )
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with (
            patch("kanon_cli.commands.install._check_pipx"),
            pytest.raises(SystemExit),
        ):
            _run(args)

    def test_repo_rev_without_url_exits(self, tmp_path) -> None:
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "REPO_REV=main\n"
            "GITBASE=https://example.com/\n"
            "KANON_SOURCE_test_URL=https://example.com/manifest.git\n"
            "KANON_SOURCE_test_REVISION=main\n"
            "KANON_SOURCE_test_PATH=repo-specs/test.xml\n"
        )
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with (
            patch("kanon_cli.commands.install._check_pipx"),
            pytest.raises(SystemExit),
        ):
            _run(args)

    def test_both_repo_url_and_rev_installs_from_git(self, tmp_path) -> None:
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "REPO_URL=https://example.com/repo.git\n"
            "REPO_REV=~=1.0.0\n"
            "GITBASE=https://example.com/\n"
            "KANON_SOURCE_test_URL=https://example.com/manifest.git\n"
            "KANON_SOURCE_test_REVISION=main\n"
            "KANON_SOURCE_test_PATH=repo-specs/test.xml\n"
        )
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with (
            patch("kanon_cli.commands.install._check_pipx"),
            patch("kanon_cli.commands.install.resolve_version", return_value="1.0.5") as mock_resolve,
            patch("kanon_cli.commands.install._install_repo_tool_from_git") as mock_git_install,
            patch("kanon_cli.commands.install.install"),
        ):
            _run(args)
            mock_resolve.assert_called_once_with("https://example.com/repo.git", "~=1.0.0")
            mock_git_install.assert_called_once_with("https://example.com/repo.git", "1.0.5")

    def test_no_repo_url_or_rev_installs_from_pypi(self, tmp_path) -> None:
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "GITBASE=https://example.com/\n"
            "KANON_SOURCE_test_URL=https://example.com/manifest.git\n"
            "KANON_SOURCE_test_REVISION=main\n"
            "KANON_SOURCE_test_PATH=repo-specs/test.xml\n"
        )
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with (
            patch("kanon_cli.commands.install._check_pipx"),
            patch("kanon_cli.commands.install._ensure_repo_tool_from_pypi") as mock_pypi,
            patch("kanon_cli.commands.install.install"),
        ):
            _run(args)
            mock_pypi.assert_called_once()

    def test_missing_kanonenv_file_exits(self, tmp_path) -> None:
        from kanon_cli.commands.install import _run

        args = MagicMock()
        args.kanonenv_path = tmp_path / "nonexistent"

        with pytest.raises(SystemExit):
            _run(args)

    def test_invalid_kanonenv_exits(self, tmp_path) -> None:
        from kanon_cli.commands.install import _run

        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("NO_SOURCES_DEFINED=true\n")
        args = MagicMock()
        args.kanonenv_path = kanonenv

        with pytest.raises(SystemExit):
            _run(args)


@pytest.mark.unit
class TestRegister:
    def test_registers_install_subcommand(self) -> None:
        from kanon_cli.commands.install import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register(subparsers)

        parsed = parser.parse_args(["install", "/tmp/test-kanonenv"])
        assert hasattr(parsed, "func")
        assert str(parsed.kanonenv_path) == "/tmp/test-kanonenv"
