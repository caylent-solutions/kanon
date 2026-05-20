"""Tests for the catalog resolution module."""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.catalog import (
    MissingCatalogSourceError,
    _clone_remote_catalog,
    _parse_catalog_source,
    resolve_catalog_dir,
)


@pytest.mark.unit
class TestMissingCatalogSourceError:
    """Verify MissingCatalogSourceError exception class (AC-FUNC-001)."""

    def test_is_subclass_of_value_error(self) -> None:
        assert issubclass(MissingCatalogSourceError, ValueError)

    def test_can_be_raised_and_caught_as_value_error(self) -> None:
        with pytest.raises(ValueError):
            raise MissingCatalogSourceError()

    def test_can_be_raised_and_caught_as_missing_catalog_source_error(self) -> None:
        with pytest.raises(MissingCatalogSourceError):
            raise MissingCatalogSourceError()

    def test_carries_no_required_fields(self) -> None:
        # Must be instantiable with no arguments (caller supplies message context)
        err = MissingCatalogSourceError()
        assert isinstance(err, MissingCatalogSourceError)


@pytest.mark.unit
class TestParseCatalogSource:
    """Verify catalog source string parsing."""

    def test_parses_https_url_with_tag(self) -> None:
        url, ref = _parse_catalog_source("https://github.com/org/repo.git@v1.0.0")
        assert url == "https://github.com/org/repo.git"
        assert ref == "v1.0.0"

    def test_parses_ssh_url_with_branch(self) -> None:
        url, ref = _parse_catalog_source("git@github.com:org/repo.git@main")
        assert url == "git@github.com:org/repo.git"
        assert ref == "main"

    def test_parses_latest(self) -> None:
        url, ref = _parse_catalog_source("https://github.com/org/repo.git@latest")
        assert url == "https://github.com/org/repo.git"
        assert ref == "latest"

    def test_missing_at_sign_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid catalog source format"):
            _parse_catalog_source("https://github.com/org/repo.git")

    def test_empty_ref_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty ref"):
            _parse_catalog_source("https://github.com/org/repo.git@")

    def test_empty_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty URL"):
            _parse_catalog_source("@main")

    def test_ambiguous_ssh_url_without_ref_raises(self) -> None:
        """SSH-style URL with no trailing @<ref> is rejected (lines 105-111 guard)."""
        with pytest.raises(ValueError, match="Invalid catalog source format"):
            _parse_catalog_source("git@host:org/repo.git")


@pytest.mark.unit
class TestResolveCatalogDir:
    """Verify catalog directory resolution priority."""

    def test_raises_missing_catalog_source_error_when_no_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-FUNC-002: no flag, no env var raises MissingCatalogSourceError."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        with pytest.raises(MissingCatalogSourceError):
            resolve_catalog_dir(None)

    def test_flag_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://env-repo.git@env-branch")
        flag_catalog = tmp_path / "repo" / "catalog"
        flag_catalog.mkdir(parents=True)

        with patch("kanon_cli.core.catalog._clone_remote_catalog") as mock_clone:
            mock_clone.return_value = flag_catalog
            result = resolve_catalog_dir("https://flag-repo.git@flag-branch")

        mock_clone.assert_called_once_with("https://flag-repo.git@flag-branch")
        assert result == flag_catalog

    def test_env_var_used_when_no_flag(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
        monkeypatch.setenv("KANON_CATALOG_SOURCE", "https://env-repo.git@env-branch")
        env_catalog = tmp_path / "repo" / "catalog"
        env_catalog.mkdir(parents=True)

        with patch("kanon_cli.core.catalog._clone_remote_catalog") as mock_clone:
            mock_clone.return_value = env_catalog
            result = resolve_catalog_dir(None)

        mock_clone.assert_called_once_with("https://env-repo.git@env-branch")
        assert result == env_catalog


@pytest.mark.unit
class TestCloneRemoteCatalog:
    """Verify remote catalog cloning."""

    def test_clones_repo_and_returns_catalog_path(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        catalog_dir = repo_dir / "catalog"
        catalog_dir.mkdir(parents=True)

        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
        ):
            mock_run.return_value.returncode = 0
            result = _clone_remote_catalog("https://github.com/org/repo.git@main")

        assert result == catalog_dir
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "git"
        assert "--branch" in cmd
        assert "main" in cmd

    def test_latest_resolves_via_version_module(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        catalog_dir = repo_dir / "catalog"
        catalog_dir.mkdir(parents=True)

        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.core.catalog.resolve_version", return_value="v2.0.0") as mock_resolve,
        ):
            mock_run.return_value.returncode = 0
            _clone_remote_catalog("https://github.com/org/repo.git@latest")

        mock_resolve.assert_called_once_with("https://github.com/org/repo.git", "*")
        cmd = mock_run.call_args[0][0]
        assert "v2.0.0" in cmd

    def test_clone_failure_exits(self) -> None:
        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value="/tmp/kanon-test"),
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "clone failed"
            with pytest.raises(SystemExit):
                _clone_remote_catalog("https://github.com/org/repo.git@main")

    def test_missing_catalog_dir_in_clone_exits(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir(parents=True)
        # No catalog/ directory inside repo

        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
        ):
            mock_run.return_value.returncode = 0
            with pytest.raises(SystemExit):
                _clone_remote_catalog("https://github.com/org/repo.git@main")

    def test_constraint_range_resolves_before_clone(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        catalog_dir = repo_dir / "catalog"
        catalog_dir.mkdir(parents=True)

        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.core.catalog.resolve_version", return_value="refs/tags/2.1.0") as mock_resolve,
        ):
            mock_run.return_value.returncode = 0
            _clone_remote_catalog("https://github.com/org/repo.git@>=2.0.0,<3.0.0")

        mock_resolve.assert_called_once_with("https://github.com/org/repo.git", ">=2.0.0,<3.0.0")
        cmd = mock_run.call_args[0][0]
        assert "2.1.0" in cmd

    def test_wildcard_constraint_resolves(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        catalog_dir = repo_dir / "catalog"
        catalog_dir.mkdir(parents=True)

        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.core.catalog.resolve_version", return_value="refs/tags/3.0.0") as mock_resolve,
        ):
            mock_run.return_value.returncode = 0
            _clone_remote_catalog("https://github.com/org/repo.git@*")

        mock_resolve.assert_called_once_with("https://github.com/org/repo.git", "*")
        cmd = mock_run.call_args[0][0]
        assert "3.0.0" in cmd

    def test_compatible_release_constraint(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        catalog_dir = repo_dir / "catalog"
        catalog_dir.mkdir(parents=True)

        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.core.catalog.resolve_version", return_value="refs/tags/2.0.3") as mock_resolve,
        ):
            mock_run.return_value.returncode = 0
            _clone_remote_catalog("https://github.com/org/repo.git@~=2.0.0")

        mock_resolve.assert_called_once_with("https://github.com/org/repo.git", "~=2.0.0")
        cmd = mock_run.call_args[0][0]
        assert "2.0.3" in cmd

    def test_exact_constraint(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        catalog_dir = repo_dir / "catalog"
        catalog_dir.mkdir(parents=True)

        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.core.catalog.resolve_version", return_value="refs/tags/2.0.0") as mock_resolve,
        ):
            mock_run.return_value.returncode = 0
            _clone_remote_catalog("https://github.com/org/repo.git@==2.0.0")

        mock_resolve.assert_called_once_with("https://github.com/org/repo.git", "==2.0.0")
        cmd = mock_run.call_args[0][0]
        assert "2.0.0" in cmd

    def test_plain_branch_skips_resolution(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        catalog_dir = repo_dir / "catalog"
        catalog_dir.mkdir(parents=True)

        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.core.catalog.resolve_version") as mock_resolve,
        ):
            mock_run.return_value.returncode = 0
            _clone_remote_catalog("https://github.com/org/repo.git@main")

        mock_resolve.assert_not_called()
        cmd = mock_run.call_args[0][0]
        assert "main" in cmd

    def test_plain_tag_skips_resolution(self, tmp_path: pathlib.Path) -> None:
        repo_dir = tmp_path / "repo"
        catalog_dir = repo_dir / "catalog"
        catalog_dir.mkdir(parents=True)

        with (
            patch("kanon_cli.core.catalog.subprocess.run") as mock_run,
            patch("kanon_cli.core.catalog.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("kanon_cli.core.catalog.resolve_version") as mock_resolve,
        ):
            mock_run.return_value.returncode = 0
            _clone_remote_catalog("https://github.com/org/repo.git@v2.0.0")

        mock_resolve.assert_not_called()
        cmd = mock_run.call_args[0][0]
        assert "v2.0.0" in cmd


# ---------------------------------------------------------------------------
# Tests for add_help=True on the 'catalog' and 'catalog audit' subparsers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCatalogSubparserHelp:
    """The 'catalog' and 'catalog audit' subparsers have add_help=True and accept '-h'."""

    def test_catalog_short_dash_h_exits_0(self) -> None:
        """kanon catalog -h exits 0 (add_help=True on the catalog subparser)."""

        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["catalog", "-h"])
        assert exc_info.value.code == 0

    def test_catalog_audit_short_dash_h_exits_0(self) -> None:
        """kanon catalog audit -h exits 0 (add_help=True on the audit sub-subparser)."""

        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["catalog", "audit", "-h"])
        assert exc_info.value.code == 0

    def test_catalog_subparser_has_add_help_true(self) -> None:
        """The 'catalog' subparser has add_help=True set explicitly."""
        import argparse

        from kanon_cli.commands.catalog import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        catalog_parser = subparsers.choices["catalog"]
        assert catalog_parser.add_help is True, "catalog subparser must have add_help=True so '-h' is accepted"

    def test_catalog_audit_subparser_has_add_help_true(self) -> None:
        """The 'catalog audit' sub-subparser has add_help=True set explicitly."""
        import argparse

        from kanon_cli.commands.catalog import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        catalog_parser = subparsers.choices["catalog"]
        for action in catalog_parser._actions:
            if hasattr(action, "choices") and action.choices and "audit" in action.choices:
                audit_parser = action.choices["audit"]
                assert audit_parser.add_help is True, (
                    "catalog audit sub-subparser must have add_help=True so '-h' is accepted"
                )
                return
        raise AssertionError("No 'audit' sub-subparser found under 'catalog'")
