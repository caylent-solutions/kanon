"""Integration tests for kanon install path resolution and auto-discovery (9 tests).

Verifies the CLI boundary behaviour of the install command for:
  - AC-TEST-001: auto-discovery of .kanon from CWD or ancestor
  - AC-TEST-002: relative path .kanon resolved to absolute (regression guard E0-INSTALL-RELATIVE)
  - AC-TEST-003: absolute path accepted unchanged
  - AC-TEST-004: relative subdir path resolved correctly
  - AC-TEST-005: missing .kanon exits 1 with ".kanon file not found" message
  - AC-FUNC-001: CLI boundary resolves relative manifests to absolute before invoking parser
  - AC-FUNC-002: auto-discovery walk matches find_kanonenv() contract
"""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.cli import main
from kanon_cli.core.discover import find_kanonenv
from tests.conftest import write_kanonenv


@pytest.mark.integration
class TestInstallAutoDiscovery:
    """AC-TEST-001 and AC-FUNC-002: auto-discovery from CWD and ancestors."""

    def test_install_auto_discovers_kanonenv_in_cwd(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install with no path argument discovers .kanon in cwd and invokes install."""
        write_kanonenv(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch("kanon_cli.commands.install.install") as mock_install:
            main(["install"])

        mock_install.assert_called_once()
        called_path: pathlib.Path = mock_install.call_args[0][0]
        assert called_path.is_absolute()
        assert called_path.name == ".kanon"
        assert called_path.parent == tmp_path.resolve()

    def test_install_auto_discovers_kanonenv_in_ancestor(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install with no path argument discovers .kanon two levels above cwd."""
        write_kanonenv(tmp_path)
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)

        with patch("kanon_cli.commands.install.install") as mock_install:
            main(["install"])

        mock_install.assert_called_once()
        called_path: pathlib.Path = mock_install.call_args[0][0]
        assert called_path == (tmp_path / ".kanon").resolve()

    def test_auto_discovery_result_matches_find_kanonenv_contract(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-FUNC-002: auto-discovery path passed to install() equals find_kanonenv() result."""
        write_kanonenv(tmp_path)
        child = tmp_path / "sub"
        child.mkdir()
        monkeypatch.chdir(child)

        with patch("kanon_cli.commands.install.install") as mock_install:
            main(["install"])

        mock_install.assert_called_once()
        called_path: pathlib.Path = mock_install.call_args[0][0]
        assert called_path == find_kanonenv(start_dir=child)


@pytest.mark.integration
class TestInstallRelativePath:
    """AC-TEST-002 and AC-FUNC-001: relative path resolved to absolute before parser."""

    def test_relative_path_dot_kanon_resolved_to_absolute(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-TEST-002: 'kanon install .kanon' resolves to absolute and invokes install."""
        write_kanonenv(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch("kanon_cli.commands.install.install") as mock_install:
            main(["install", ".kanon"])

        mock_install.assert_called_once()
        called_path: pathlib.Path = mock_install.call_args[0][0]
        assert called_path.is_absolute(), "CLI must resolve relative .kanon to absolute before invoking install()"
        assert called_path == (tmp_path / ".kanon").resolve()

    def test_relative_path_resolves_to_absolute_before_parser(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-FUNC-001: install() receives an absolute Path regardless of relative CLI argument."""
        write_kanonenv(tmp_path)
        monkeypatch.chdir(tmp_path)

        received_paths: list[pathlib.Path] = []

        def capture_path(path: pathlib.Path) -> None:
            received_paths.append(path)

        with patch("kanon_cli.commands.install.install", side_effect=capture_path):
            main(["install", ".kanon"])

        assert len(received_paths) == 1
        assert received_paths[0].is_absolute(), (
            "AC-FUNC-001: CLI boundary must resolve relative paths to absolute before invoking install()"
        )


@pytest.mark.integration
class TestInstallAbsolutePath:
    """AC-TEST-003: absolute path accepted and passed through correctly."""

    def test_absolute_path_accepted_and_passed_to_install(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: 'kanon install /abs/.kanon' accepted and passed as absolute to install()."""
        kanonenv = write_kanonenv(tmp_path)
        absolute_path = str(kanonenv)
        assert pathlib.Path(absolute_path).is_absolute()

        with patch("kanon_cli.commands.install.install") as mock_install:
            main(["install", absolute_path])

        mock_install.assert_called_once()
        called_path: pathlib.Path = mock_install.call_args[0][0]
        assert called_path.is_absolute()
        assert called_path == kanonenv.resolve()


@pytest.mark.integration
class TestInstallRelativeSubdirPath:
    """AC-TEST-004: relative subdir path resolved correctly."""

    def test_relative_subdir_path_resolved_correctly(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-TEST-004: 'kanon install subdir/.kanon' resolves relative subdir to absolute."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        write_kanonenv(subdir)
        monkeypatch.chdir(tmp_path)

        with patch("kanon_cli.commands.install.install") as mock_install:
            main(["install", "subdir/.kanon"])

        mock_install.assert_called_once()
        called_path: pathlib.Path = mock_install.call_args[0][0]
        assert called_path.is_absolute()
        assert called_path == (subdir / ".kanon").resolve()


@pytest.mark.integration
class TestInstallMissingKanonenv:
    """AC-TEST-005: missing .kanon exits 1 with clear error message."""

    def test_missing_kanonenv_exits_1_with_not_found_message(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-TEST-005: 'kanon install' with missing .kanon exits 1 with '.kanon file not found'."""
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            main(["install"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "No .kanon file found" in captured.err, (
            f"Expected 'No .kanon file found' in stderr, got: {captured.err!r}"
        )

    def test_explicit_missing_path_exits_1_with_not_found_message(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-TEST-005: 'kanon install /nonexistent/.kanon' exits 1 with '.kanon file not found'."""
        nonexistent = str(tmp_path / "nonexistent" / ".kanon")

        with pytest.raises(SystemExit) as exc_info:
            main(["install", nonexistent])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert ".kanon file not found" in captured.err, (
            f"Expected '.kanon file not found' in stderr, got: {captured.err!r}"
        )
