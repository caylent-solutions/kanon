"""Integration tests for automatic .kanon source discovery (12 tests).

Exercises find_kanonenv() by creating real directory trees and verifying that
the discovery walk behaves correctly across directory levels and edge cases.
"""

from pathlib import Path

import pytest

from kanon_cli.core.discover import find_kanonenv


# ---------------------------------------------------------------------------
# AC-FUNC-005: Auto-discovery integration tests (12 tests)
# ---------------------------------------------------------------------------


def _write_kanonenv(directory: Path) -> Path:
    """Write a minimal .kanon file in directory and return its path."""
    kanonenv = directory / ".kanon"
    kanonenv.write_text(
        "KANON_SOURCE_s_URL=https://example.com/s.git\nKANON_SOURCE_s_REVISION=main\nKANON_SOURCE_s_PATH=m.xml\n"
    )
    return kanonenv


@pytest.mark.integration
class TestFindKanonenvCurrentDir:
    """Verify discovery within the start directory itself."""

    def test_finds_in_start_dir(self, tmp_path: Path) -> None:
        expected = _write_kanonenv(tmp_path)
        result = find_kanonenv(start_dir=tmp_path)
        assert result == expected.resolve()

    def test_returns_absolute_path(self, tmp_path: Path) -> None:
        _write_kanonenv(tmp_path)
        result = find_kanonenv(start_dir=tmp_path)
        assert result.is_absolute()

    def test_uses_cwd_when_no_start_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        expected = _write_kanonenv(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = find_kanonenv()
        assert result == expected.resolve()


@pytest.mark.integration
class TestFindKanonenvParentTraversal:
    """Verify discovery traversal walks up the directory tree."""

    def test_finds_one_level_up(self, tmp_path: Path) -> None:
        expected = _write_kanonenv(tmp_path)
        child = tmp_path / "child"
        child.mkdir()
        result = find_kanonenv(start_dir=child)
        assert result == expected.resolve()

    def test_finds_two_levels_up(self, tmp_path: Path) -> None:
        expected = _write_kanonenv(tmp_path)
        grandchild = tmp_path / "a" / "b"
        grandchild.mkdir(parents=True)
        result = find_kanonenv(start_dir=grandchild)
        assert result == expected.resolve()

    def test_finds_three_levels_up(self, tmp_path: Path) -> None:
        expected = _write_kanonenv(tmp_path)
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        result = find_kanonenv(start_dir=deep)
        assert result == expected.resolve()

    def test_stops_at_nearest_ancestor(self, tmp_path: Path) -> None:
        _write_kanonenv(tmp_path)
        child = tmp_path / "child"
        child.mkdir()
        nearest = _write_kanonenv(child)
        result = find_kanonenv(start_dir=child)
        assert result == nearest.resolve()


@pytest.mark.integration
class TestFindKanonenvNotFound:
    """Verify fail-fast behaviour when no .kanon is found."""

    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError):
            find_kanonenv(start_dir=empty)

    def test_error_message_mentions_bootstrap(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError, match="kanon bootstrap kanon"):
            find_kanonenv(start_dir=empty)

    def test_error_message_mentions_start_dir(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError, match=str(empty)):
            find_kanonenv(start_dir=empty)

    def test_ignores_directory_named_dot_kanon(self, tmp_path: Path) -> None:
        kanon_dir = tmp_path / ".kanon"
        kanon_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            find_kanonenv(start_dir=tmp_path)

    def test_suggests_explicit_path_in_error(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError, match="explicit path"):
            find_kanonenv(start_dir=empty)
