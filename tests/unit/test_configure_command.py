"""Tests for the configure command handler."""

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestCheckPipx:
    def test_pipx_missing_exits(self) -> None:
        from rpm_cli.commands.configure import _check_pipx

        with patch("rpm_cli.commands.configure.shutil.which", return_value=None):
            with pytest.raises(SystemExit):
                _check_pipx()

    def test_pipx_present_ok(self) -> None:
        from rpm_cli.commands.configure import _check_pipx

        with patch("rpm_cli.commands.configure.shutil.which", return_value="/usr/bin/pipx"):
            _check_pipx()


@pytest.mark.unit
class TestInstallRepoToolFromGit:
    def test_success(self) -> None:
        from rpm_cli.commands.configure import _install_repo_tool_from_git

        with patch("rpm_cli.commands.configure.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            _install_repo_tool_from_git("https://example.com/repo.git", "v2.0.0")
            cmd = mock_run.call_args[0][0]
            assert "pipx" in cmd
            assert "--force" in cmd
            assert "git+https://example.com/repo.git@v2.0.0" in cmd

    def test_failure_exits(self) -> None:
        from rpm_cli.commands.configure import _install_repo_tool_from_git

        with patch("rpm_cli.commands.configure.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            with pytest.raises(SystemExit):
                _install_repo_tool_from_git("https://example.com/repo.git", "v2.0.0")


@pytest.mark.unit
class TestIsRepoToolInstalled:
    def test_installed_returns_true(self) -> None:
        from rpm_cli.commands.configure import _is_repo_tool_installed

        pipx_json = json.dumps({"venvs": {"rpm-git-repo": {}}})
        with patch("rpm_cli.commands.configure.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=pipx_json)
            assert _is_repo_tool_installed() is True

    def test_not_installed_returns_false(self) -> None:
        from rpm_cli.commands.configure import _is_repo_tool_installed

        pipx_json = json.dumps({"venvs": {"some-other-package": {}}})
        with patch("rpm_cli.commands.configure.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=pipx_json)
            assert _is_repo_tool_installed() is False

    def test_empty_venvs_returns_false(self) -> None:
        from rpm_cli.commands.configure import _is_repo_tool_installed

        pipx_json = json.dumps({"venvs": {}})
        with patch("rpm_cli.commands.configure.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=pipx_json)
            assert _is_repo_tool_installed() is False

    def test_pipx_failure_exits(self) -> None:
        from rpm_cli.commands.configure import _is_repo_tool_installed

        with patch("rpm_cli.commands.configure.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="err")
            with pytest.raises(SystemExit):
                _is_repo_tool_installed()

    def test_invalid_json_exits(self) -> None:
        from rpm_cli.commands.configure import _is_repo_tool_installed

        with patch("rpm_cli.commands.configure.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="not json")
            with pytest.raises(SystemExit):
                _is_repo_tool_installed()

    def test_missing_venvs_key_exits(self) -> None:
        from rpm_cli.commands.configure import _is_repo_tool_installed

        pipx_json = json.dumps({"unexpected": "structure"})
        with patch("rpm_cli.commands.configure.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=pipx_json)
            with pytest.raises(SystemExit):
                _is_repo_tool_installed()


@pytest.mark.unit
class TestEnsureRepoToolFromPypi:
    def test_already_installed_skips(self) -> None:
        from rpm_cli.commands.configure import _ensure_repo_tool_from_pypi

        with patch("rpm_cli.commands.configure._is_repo_tool_installed", return_value=True):
            with patch("rpm_cli.commands.configure.subprocess.run") as mock_run:
                _ensure_repo_tool_from_pypi()
                mock_run.assert_not_called()

    def test_not_installed_calls_pipx_install(self) -> None:
        from rpm_cli.commands.configure import _ensure_repo_tool_from_pypi

        with patch("rpm_cli.commands.configure._is_repo_tool_installed", return_value=False):
            with patch("rpm_cli.commands.configure.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                _ensure_repo_tool_from_pypi()
                cmd = mock_run.call_args[0][0]
                assert "pipx" in cmd
                assert "install" in cmd
                assert "rpm-git-repo" in cmd
                assert "--force" not in cmd

    def test_install_failure_exits(self) -> None:
        from rpm_cli.commands.configure import _ensure_repo_tool_from_pypi

        with patch("rpm_cli.commands.configure._is_repo_tool_installed", return_value=False):
            with patch("rpm_cli.commands.configure.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stderr="error")
                with pytest.raises(SystemExit):
                    _ensure_repo_tool_from_pypi()


@pytest.mark.unit
class TestRunPartialConfig:
    def test_repo_url_without_rev_exits(self, tmp_path) -> None:
        from rpm_cli.commands.configure import _run

        rpmenv = tmp_path / ".rpmenv"
        rpmenv.write_text(
            "REPO_URL=https://example.com/repo.git\n"
            "GITBASE=https://example.com/\n"
            "RPM_SOURCE_test_URL=https://example.com/manifest.git\n"
            "RPM_SOURCE_test_REVISION=main\n"
            "RPM_SOURCE_test_PATH=repo-specs/test.xml\n"
        )
        args = MagicMock()
        args.rpmenv_path = rpmenv

        with (
            patch("rpm_cli.commands.configure._check_pipx"),
            pytest.raises(SystemExit),
        ):
            _run(args)

    def test_repo_rev_without_url_exits(self, tmp_path) -> None:
        from rpm_cli.commands.configure import _run

        rpmenv = tmp_path / ".rpmenv"
        rpmenv.write_text(
            "REPO_REV=main\n"
            "GITBASE=https://example.com/\n"
            "RPM_SOURCE_test_URL=https://example.com/manifest.git\n"
            "RPM_SOURCE_test_REVISION=main\n"
            "RPM_SOURCE_test_PATH=repo-specs/test.xml\n"
        )
        args = MagicMock()
        args.rpmenv_path = rpmenv

        with (
            patch("rpm_cli.commands.configure._check_pipx"),
            pytest.raises(SystemExit),
        ):
            _run(args)
