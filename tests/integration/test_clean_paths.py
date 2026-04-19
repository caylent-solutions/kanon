"""Integration tests for kanon clean path resolution and auto-discovery (6 tests).

Verifies the CLI boundary behaviour of the clean command for:
  - AC-TEST-001: auto-discovery of .kanon from CWD or ancestor
  - AC-TEST-002: relative path .kanon resolved to absolute (regression guard E0-INSTALL-RELATIVE clean variant)
  - AC-TEST-003: absolute path accepted unchanged
  - AC-TEST-004: missing .kanon exits 1 with stderr message
  - AC-FUNC-001: clean CLI boundary mirrors install CLI boundary for path resolution
  - AC-CHANNEL-001: stdout vs stderr discipline verified (no cross-channel leakage)
"""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.cli import main
from kanon_cli.core.discover import find_kanonenv


_MINIMAL_KANONENV = (
    "KANON_SOURCE_s_URL=https://example.com/s.git\nKANON_SOURCE_s_REVISION=main\nKANON_SOURCE_s_PATH=m.xml\n"
)


def _write_kanonenv(directory: pathlib.Path) -> pathlib.Path:
    """Write a minimal valid .kanon file in directory and return its path."""
    kanonenv = directory / ".kanon"
    kanonenv.write_text(_MINIMAL_KANONENV)
    return kanonenv


@pytest.mark.integration
class TestCleanAutoDiscovery:
    """AC-TEST-001: auto-discovery of .kanon from CWD."""

    def test_clean_auto_discovers_kanonenv_in_cwd(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-TEST-001: clean with no path argument discovers .kanon in cwd and invokes clean."""
        _write_kanonenv(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch("kanon_cli.commands.clean.clean") as mock_clean:
            main(["clean"])

        mock_clean.assert_called_once()
        called_path: pathlib.Path = mock_clean.call_args[0][0]
        assert called_path.is_absolute()
        assert called_path.name == ".kanon"
        assert called_path.parent == tmp_path.resolve()

    def test_clean_auto_discovers_kanonenv_in_ancestor(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-TEST-001: clean with no path argument discovers .kanon two levels above cwd."""
        _write_kanonenv(tmp_path)
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)

        with patch("kanon_cli.commands.clean.clean") as mock_clean:
            main(["clean"])

        mock_clean.assert_called_once()
        called_path: pathlib.Path = mock_clean.call_args[0][0]
        assert called_path == (tmp_path / ".kanon").resolve()


@pytest.mark.integration
class TestCleanRelativePath:
    """AC-TEST-002 and AC-FUNC-001: relative path resolved to absolute before core clean."""

    def test_relative_path_dot_kanon_resolved_to_absolute(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-TEST-002: 'kanon clean .kanon' resolves to absolute and invokes clean."""
        _write_kanonenv(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch("kanon_cli.commands.clean.clean") as mock_clean:
            main(["clean", ".kanon"])

        mock_clean.assert_called_once()
        called_path: pathlib.Path = mock_clean.call_args[0][0]
        assert called_path.is_absolute(), "CLI must resolve relative .kanon to absolute before invoking clean()"
        assert called_path == (tmp_path / ".kanon").resolve()

    def test_relative_path_resolves_to_absolute_before_core(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-FUNC-001: clean() receives an absolute Path regardless of relative CLI argument."""
        _write_kanonenv(tmp_path)
        monkeypatch.chdir(tmp_path)

        received_paths: list[pathlib.Path] = []

        def capture_path(path: pathlib.Path) -> None:
            received_paths.append(path)

        with patch("kanon_cli.commands.clean.clean", side_effect=capture_path):
            main(["clean", ".kanon"])

        assert len(received_paths) == 1
        assert received_paths[0].is_absolute(), (
            "AC-FUNC-001: CLI boundary must resolve relative paths to absolute before invoking clean()"
        )


@pytest.mark.integration
class TestCleanAbsolutePath:
    """AC-TEST-003: absolute path accepted and passed through correctly."""

    def test_absolute_path_accepted_and_passed_to_clean(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: 'kanon clean /abs/.kanon' accepted and passed as absolute to clean()."""
        kanonenv = _write_kanonenv(tmp_path)
        absolute_path = str(kanonenv)
        assert pathlib.Path(absolute_path).is_absolute()

        with patch("kanon_cli.commands.clean.clean") as mock_clean:
            main(["clean", absolute_path])

        mock_clean.assert_called_once()
        called_path: pathlib.Path = mock_clean.call_args[0][0]
        assert called_path.is_absolute()
        assert called_path == kanonenv.resolve()


@pytest.mark.integration
class TestCleanMissingKanonenv:
    """AC-TEST-004 and AC-CHANNEL-001: missing .kanon exits 1 with stderr message only."""

    def test_missing_kanonenv_auto_discovery_exits_1_with_stderr_message(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-TEST-004: 'kanon clean' with missing .kanon exits 1 with error on stderr."""
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            main(["clean"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert ".kanon" in captured.err, f"Expected '.kanon' in stderr, got: {captured.err!r}"
        assert captured.out == "", (
            f"AC-CHANNEL-001: error output must go to stderr only, not stdout; stdout={captured.out!r}"
        )

    def test_explicit_missing_path_exits_1_with_stderr_message(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-TEST-004: 'kanon clean /nonexistent/.kanon' exits 1 with '.kanon file not found' on stderr."""
        nonexistent = str(tmp_path / "nonexistent" / ".kanon")

        with pytest.raises(SystemExit) as exc_info:
            main(["clean", nonexistent])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert ".kanon file not found" in captured.err, (
            f"Expected '.kanon file not found' in stderr, got: {captured.err!r}"
        )
        assert captured.out == "", (
            f"AC-CHANNEL-001: error output must go to stderr only, not stdout; stdout={captured.out!r}"
        )

    def test_auto_discovery_success_message_goes_to_stdout(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: discovery success message goes to stdout, not stderr."""
        _write_kanonenv(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch("kanon_cli.commands.clean.clean"):
            main(["clean"])

        captured = capsys.readouterr()
        assert captured.err == "", f"AC-CHANNEL-001: no error output expected on success; stderr={captured.err!r}"
        assert "clean" in captured.out.lower() or ".kanon" in captured.out, (
            f"AC-CHANNEL-001: success discovery message expected on stdout; stdout={captured.out!r}"
        )

    def test_auto_discovery_find_kanonenv_contract_matches(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-FUNC-001: path passed to clean() equals find_kanonenv() result from the same cwd."""
        _write_kanonenv(tmp_path)
        child = tmp_path / "sub"
        child.mkdir()
        monkeypatch.chdir(child)

        with patch("kanon_cli.commands.clean.clean") as mock_clean:
            main(["clean"])

        mock_clean.assert_called_once()
        called_path: pathlib.Path = mock_clean.call_args[0][0]
        assert called_path == find_kanonenv(start_dir=child)
