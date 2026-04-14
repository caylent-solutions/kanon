"""Tests for .kanon file auto-discovery."""

from pathlib import Path

import pytest

from kanon_cli.core.discover import find_kanonenv


@pytest.mark.unit
class TestFindKanonenvInCurrentDir:
    def test_finds_kanonenv_in_start_dir(self, tmp_path: Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("KANON_MARKETPLACE_INSTALL=false\n")

        result = find_kanonenv(start_dir=tmp_path)
        assert result == kanonenv.resolve()

    def test_returns_absolute_path(self, tmp_path: Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("KANON_MARKETPLACE_INSTALL=false\n")

        result = find_kanonenv(start_dir=tmp_path)
        assert result.is_absolute()


@pytest.mark.unit
class TestFindKanonenvInParent:
    def test_finds_kanonenv_one_level_up(self, tmp_path: Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("KANON_MARKETPLACE_INSTALL=false\n")
        child = tmp_path / "subdir"
        child.mkdir()

        result = find_kanonenv(start_dir=child)
        assert result == kanonenv.resolve()

    def test_finds_kanonenv_two_levels_up(self, tmp_path: Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("KANON_MARKETPLACE_INSTALL=false\n")
        grandchild = tmp_path / "a" / "b"
        grandchild.mkdir(parents=True)

        result = find_kanonenv(start_dir=grandchild)
        assert result == kanonenv.resolve()


@pytest.mark.unit
class TestFindKanonenvNearest:
    def test_stops_at_nearest(self, tmp_path: Path) -> None:
        root_kanonenv = tmp_path / ".kanon"
        root_kanonenv.write_text("root\n")
        child = tmp_path / "subdir"
        child.mkdir()
        child_kanonenv = child / ".kanon"
        child_kanonenv.write_text("child\n")

        result = find_kanonenv(start_dir=child)
        assert result == child_kanonenv.resolve()


@pytest.mark.unit
class TestFindKanonenvNotFound:
    def test_raises_when_not_found(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="No .kanon file found"):
            find_kanonenv(start_dir=empty_dir)

    def test_error_message_includes_start_dir(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with pytest.raises(FileNotFoundError, match=str(empty_dir)):
            find_kanonenv(start_dir=empty_dir)

    def test_error_message_suggests_bootstrap(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="kanon bootstrap kanon"):
            find_kanonenv(start_dir=empty_dir)


@pytest.mark.unit
class TestFindKanonenvDefaultDir:
    def test_uses_cwd_by_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("KANON_MARKETPLACE_INSTALL=false\n")
        monkeypatch.chdir(tmp_path)

        result = find_kanonenv()
        assert result == kanonenv.resolve()

    def test_ignores_directories_named_kanon(self, tmp_path: Path) -> None:
        kanon_dir = tmp_path / ".kanon"
        kanon_dir.mkdir()

        with pytest.raises(FileNotFoundError):
            find_kanonenv(start_dir=tmp_path)
