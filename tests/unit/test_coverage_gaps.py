"""Tests to close coverage gaps identified in E0-F9-S2-T3.

Covers:
- commands/validate.py lines 75-80: _run_validate_help when validate_command is None
- core/install.py line 187: update_gitignore when content does not end with newline
- core/install.py line 204: prepare_marketplace_dir with symlink or non-directory item
"""

import pathlib
import types

import pytest

from kanon_cli.commands.validate import _run_validate_help
from kanon_cli.core.install import prepare_marketplace_dir, update_gitignore


@pytest.mark.unit
class TestRunValidateHelp:
    """Tests for _run_validate_help when no sub-subcommand is given."""

    def test_exits_with_code_2_when_no_validate_command(self) -> None:
        """Lines 75-80: sys.exit(2) when args.validate_command is None."""
        args = types.SimpleNamespace(validate_command=None)
        with pytest.raises(SystemExit) as exc_info:
            _run_validate_help(args)
        assert exc_info.value.code == 2

    def test_error_message_printed_to_stderr(self, capsys) -> None:
        """Lines 76-79: error message is printed to stderr."""
        args = types.SimpleNamespace(validate_command=None)
        with pytest.raises(SystemExit):
            _run_validate_help(args)
        captured = capsys.readouterr()
        assert "Must specify a validation target" in captured.err
        assert "xml" in captured.err
        assert "marketplace" in captured.err

    def test_no_exit_when_validate_command_is_set(self) -> None:
        """_run_validate_help does not exit when a sub-command is present."""
        args = types.SimpleNamespace(validate_command="xml")
        _run_validate_help(args)


@pytest.mark.unit
class TestUpdateGitignoreNoTrailingNewline:
    """Tests for update_gitignore when existing content has no trailing newline."""

    def test_adds_newline_before_entries_when_content_lacks_trailing_newline(self, tmp_path: pathlib.Path) -> None:
        """Line 187: f.write('\\n') when existing content does not end with '\\n'."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("some-existing-entry")
        update_gitignore(tmp_path)
        content = gitignore.read_text()
        lines = content.splitlines()
        assert "some-existing-entry" in lines
        assert ".packages/" in lines
        assert ".kanon-data/" in lines

    def test_content_after_update_is_valid_per_line(self, tmp_path: pathlib.Path) -> None:
        """Each entry must be on its own line when preceded by no-newline content."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("custom-entry")
        update_gitignore(tmp_path)
        content = gitignore.read_text()
        assert content.startswith("custom-entry")
        assert ".packages/" in content
        assert ".kanon-data/" in content
        lines = content.splitlines()
        assert "custom-entry" in lines
        assert ".packages/" in lines


@pytest.mark.unit
class TestPrepareMarketplaceDirSymlinkAndFile:
    """Tests for prepare_marketplace_dir with symlink and non-directory items."""

    def test_removes_symlink_in_marketplace_dir(self, tmp_path: pathlib.Path) -> None:
        """Line 204: item.unlink() when item is a symlink."""
        mp_dir = tmp_path / "mp"
        mp_dir.mkdir()
        target = tmp_path / "target_file.txt"
        target.write_text("data")
        link = mp_dir / "symlink"
        link.symlink_to(target)
        assert link.is_symlink()
        prepare_marketplace_dir(mp_dir)
        assert not link.exists()
        assert not link.is_symlink()

    def test_removes_regular_file_in_marketplace_dir(self, tmp_path: pathlib.Path) -> None:
        """Line 204: item.unlink() when item is a non-directory regular file."""
        mp_dir = tmp_path / "mp"
        mp_dir.mkdir()
        regular_file = mp_dir / "some_file.txt"
        regular_file.write_text("content")
        prepare_marketplace_dir(mp_dir)
        assert not regular_file.exists()

    def test_removes_directory_in_marketplace_dir(self, tmp_path: pathlib.Path) -> None:
        """Existing subdirectory is removed via shutil.rmtree."""
        mp_dir = tmp_path / "mp"
        mp_dir.mkdir()
        sub_dir = mp_dir / "subdir"
        sub_dir.mkdir()
        (sub_dir / "nested.txt").write_text("nested")
        prepare_marketplace_dir(mp_dir)
        assert not sub_dir.exists()

    def test_marketplace_dir_empty_after_cleanup(self, tmp_path: pathlib.Path) -> None:
        """Marketplace dir is fully empty after prepare regardless of content type."""
        mp_dir = tmp_path / "mp"
        mp_dir.mkdir()
        (mp_dir / "file1.txt").write_text("a")
        sub = mp_dir / "subdir"
        sub.mkdir()
        (sub / "file2.txt").write_text("b")
        target = tmp_path / "link_target"
        target.write_text("c")
        (mp_dir / "link").symlink_to(target)
        prepare_marketplace_dir(mp_dir)
        assert list(mp_dir.iterdir()) == []
