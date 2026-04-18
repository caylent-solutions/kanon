"""Integration tests for .gitignore idempotency in the kanon install workflow.

Verifies that update_gitignore correctly handles all edge cases:

AC-TEST-001: preexisting .gitignore with kanon entries is not double-written
AC-TEST-002: missing .gitignore is created on first install
AC-TEST-003: malformed .gitignore is handled gracefully
AC-TEST-004: .gitignore without trailing newline is appended cleanly
"""

import pathlib

import pytest

from kanon_cli.core.install import update_gitignore

_KANON_ENTRIES = [".packages/", ".kanon-data/"]


@pytest.mark.integration
class TestGitignoreIdempotency:
    """Verify .gitignore update behavior is idempotent and handles edge cases."""

    def test_existing_gitignore_with_kanon_entries_not_double_written(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-001: calling update_gitignore twice does not duplicate entries."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".packages/\n.kanon-data/\n")

        update_gitignore(tmp_path)
        content_after_first = gitignore.read_text()

        update_gitignore(tmp_path)
        content_after_second = gitignore.read_text()

        assert content_after_first == content_after_second, (
            "update_gitignore must be idempotent: content changed on second call"
        )
        assert content_after_second.count(".packages/") == 1, (
            ".packages/ must appear exactly once in .gitignore after two calls"
        )
        assert content_after_second.count(".kanon-data/") == 1, (
            ".kanon-data/ must appear exactly once in .gitignore after two calls"
        )

    @pytest.mark.parametrize("entry", _KANON_ENTRIES)
    def test_existing_gitignore_entry_not_duplicated_per_entry(self, tmp_path: pathlib.Path, entry: str) -> None:
        """AC-TEST-001 (parametrized): each kanon entry is never duplicated."""
        gitignore = tmp_path / ".gitignore"
        initial_content = "\n".join(_KANON_ENTRIES) + "\n"
        gitignore.write_text(initial_content)

        for _ in range(3):
            update_gitignore(tmp_path)

        content = gitignore.read_text()
        assert content.count(entry) == 1, (
            f"{entry!r} must appear exactly once even after multiple update_gitignore calls"
        )

    def test_missing_gitignore_is_created_on_first_install(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: update_gitignore creates .gitignore when it does not exist."""
        gitignore = tmp_path / ".gitignore"
        assert not gitignore.exists(), "Precondition: .gitignore must not exist before test"

        update_gitignore(tmp_path)

        assert gitignore.exists(), ".gitignore must be created by update_gitignore"
        content = gitignore.read_text()
        for entry in _KANON_ENTRIES:
            assert entry in content, f"{entry!r} must be present in the newly created .gitignore"

    def test_missing_gitignore_contains_all_required_entries(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: newly created .gitignore contains all required kanon entries."""
        update_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text()

        lines = content.splitlines()
        for entry in _KANON_ENTRIES:
            assert entry in lines, f"{entry!r} must appear as a standalone line in the new .gitignore"

    def test_malformed_gitignore_is_handled_gracefully(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-003: a .gitignore with no trailing newline and binary-like content is handled."""
        gitignore = tmp_path / ".gitignore"
        # Malformed content: non-UTF-8 bytes are not expected by update_gitignore,
        # but a file with unusual whitespace, blank lines, and mixed line endings
        # is a realistic malformed case that should be handled without error.
        malformed_content = "# Project ignores\r\n\r\nbuild/\r\ndist/\n\t\nnode_modules/"
        gitignore.write_text(malformed_content, encoding="utf-8")

        # Must not raise any exception
        update_gitignore(tmp_path)

        content = gitignore.read_text(encoding="utf-8")
        for entry in _KANON_ENTRIES:
            assert entry in content, f"{entry!r} must be appended even when .gitignore had malformed content"

    def test_malformed_gitignore_existing_content_preserved(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-003: malformed .gitignore original content is preserved after update."""
        gitignore = tmp_path / ".gitignore"
        original_lines = ["build/", "dist/", "node_modules/"]
        gitignore.write_text("\n".join(original_lines) + "\n")

        update_gitignore(tmp_path)

        content = gitignore.read_text()
        for line in original_lines:
            assert line in content, f"Original line {line!r} must be preserved in .gitignore after update"

    def test_gitignore_without_trailing_newline_appended_cleanly(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-004: entries are appended on their own line when .gitignore has no trailing newline."""
        gitignore = tmp_path / ".gitignore"
        # No trailing newline
        gitignore.write_text("build/")

        update_gitignore(tmp_path)

        content = gitignore.read_text()
        lines = content.splitlines()
        assert "build/" in lines, "Pre-existing 'build/' entry must remain on its own line"
        for entry in _KANON_ENTRIES:
            assert entry in lines, (
                f"{entry!r} must appear on its own line after appending to a file without trailing newline"
            )

    def test_gitignore_without_trailing_newline_entries_not_concatenated(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-004: kanon entries must not be concatenated onto the last line."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("build/")

        update_gitignore(tmp_path)

        content = gitignore.read_text()
        # "build/.packages/" would indicate concatenation -- it must not occur
        assert "build/.packages/" not in content, (
            "Kanon entries must not be concatenated with the last line of a file missing trailing newline"
        )
        assert "build/.kanon-data/" not in content, (
            "Kanon entries must not be concatenated with the last line of a file missing trailing newline"
        )

    def test_gitignore_entries_each_on_own_line(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-004: each kanon entry written by update_gitignore occupies its own line."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("build/")

        update_gitignore(tmp_path)

        lines = gitignore.read_text().splitlines()
        for entry in _KANON_ENTRIES:
            assert entry in lines, f"{entry!r} must be a standalone line in the .gitignore output"
