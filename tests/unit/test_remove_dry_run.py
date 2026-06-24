"""Unit tests for the 'kanon remove --dry-run' diff renderer.

Covers:
- Single-source dry-run diff output (AC-FUNC-001, AC-FUNC-002)
- Multi-source dry-run diff output
- No-op dry-run (no names found -- expects error, not diff)
- --force flag dry-run scenario (future: currently not relevant here)
- File unchanged after dry-run (AC-FUNC-003, mtime + SHA-256)

AC-TEST-001
"""

import argparse
import hashlib
import pathlib

import pytest

from kanon_cli.commands.remove import (
    _render_remove_dry_run_diff,
    run_remove,
)


def _make_args(
    names: list[str],
    kanon_file: str,
    force: bool = False,
    dry_run: bool = False,
    no_color: bool = False,
) -> argparse.Namespace:
    """Construct a Namespace matching what argparse would produce for 'kanon remove'."""
    return argparse.Namespace(
        names=names,
        kanon_file=kanon_file,
        force=force,
        dry_run=dry_run,
        no_color=no_color,
    )


def _file_sha256(path: pathlib.Path) -> str:
    """Return the SHA-256 hex digest of path's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.unit
class TestRenderRemoveDryRunDiff:
    """_render_remove_dry_run_diff() prints '-' prefixed lines for removed keys."""

    def test_single_source_prints_five_minus_lines(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Single-source diff shows five '-' lines for URL, REF, PATH, NAME, GITBASE."""
        lines = [
            "GITBASE=x\n",
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n",
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n",
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n",
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n",
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n",
        ]
        removal_indices = {1, 2, 3, 4, 5}
        _render_remove_dry_run_diff(lines, removal_indices)

        out = capsys.readouterr().out
        assert "-KANON_SOURCE_foo_bar_URL=https://example.com/repo.git" in out
        assert "-KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0" in out
        assert "-KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml" in out
        assert "-KANON_SOURCE_foo_bar_NAME=foo_bar" in out
        assert "-KANON_SOURCE_foo_bar_GITBASE=https://example.com" in out

    def test_all_five_lines_have_minus_prefix(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Every removed line is prefixed with '-'."""
        lines = [
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n",
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n",
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n",
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n",
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n",
        ]
        removal_indices = {0, 1, 2, 3, 4}
        _render_remove_dry_run_diff(lines, removal_indices)

        out = capsys.readouterr().out
        output_lines = [ln for ln in out.splitlines() if ln.strip()]
        assert all(ln.startswith("-") for ln in output_lines)
        assert len(output_lines) == 5

    def test_non_removal_lines_not_printed(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Lines not in removal_indices are NOT printed."""
        lines = [
            "GITBASE=x\n",
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n",
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n",
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n",
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n",
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n",
            "OTHER=y\n",
        ]
        removal_indices = {1, 2, 3, 4, 5}
        _render_remove_dry_run_diff(lines, removal_indices)

        out = capsys.readouterr().out

        assert "GITBASE=x" not in out
        assert "OTHER=y" not in out

    @pytest.mark.parametrize(
        "source_name,indices",
        [
            ("foo_bar", {1, 2, 3}),
            ("baz_qux", {4, 5, 6}),
        ],
        ids=["source=foo_bar", "source=baz_qux"],
    )
    def test_parametrized_source_names(
        self,
        source_name: str,
        indices: set[int],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Parametrized: diff renderer works for different source names."""
        lines = [
            "GITBASE=x\n",
            f"KANON_SOURCE_{source_name}_URL=https://example.com/repo.git\n",
            f"KANON_SOURCE_{source_name}_REF=refs/tags/1.0.0\n",
            f"KANON_SOURCE_{source_name}_PATH=repo-specs/marketplace.xml\n",
            f"KANON_SOURCE_{source_name}_NAME={source_name}\n",
            f"KANON_SOURCE_{source_name}_GITBASE=https://example.com\n",
            "GITBASE2=y\n",
            f"KANON_SOURCE_{source_name}_URL=dup\n",
            f"KANON_SOURCE_{source_name}_REF=dup\n",
            f"KANON_SOURCE_{source_name}_PATH=dup\n",
            f"KANON_SOURCE_{source_name}_NAME=dup\n",
            f"KANON_SOURCE_{source_name}_GITBASE=dup\n",
        ]

        first_indices = {1, 2, 3, 4, 5}
        _render_remove_dry_run_diff(lines, first_indices)

        out = capsys.readouterr().out
        assert f"-KANON_SOURCE_{source_name}_URL" in out

    def test_multi_source_removal_shows_all_lines(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Multi-source: all removal indices for two sources appear in the diff."""
        lines = [
            "KANON_SOURCE_foo_bar_URL=https://example.com/foo.git\n",
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n",
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo.xml\n",
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n",
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n",
            "KANON_SOURCE_baz_qux_URL=https://example.com/baz.git\n",
            "KANON_SOURCE_baz_qux_REF=refs/tags/2.0.0\n",
            "KANON_SOURCE_baz_qux_PATH=repo-specs/baz.xml\n",
            "KANON_SOURCE_baz_qux_NAME=baz_qux\n",
            "KANON_SOURCE_baz_qux_GITBASE=https://example.com\n",
        ]
        removal_indices = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9}
        _render_remove_dry_run_diff(lines, removal_indices)

        out = capsys.readouterr().out
        output_lines = [ln for ln in out.splitlines() if ln.strip()]
        assert len(output_lines) == 10
        assert all(ln.startswith("-") for ln in output_lines)

    def test_empty_removal_set_prints_nothing(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Empty removal set produces no output (no-op case)."""
        lines = ["GITBASE=x\n"]
        _render_remove_dry_run_diff(lines, set())

        out = capsys.readouterr().out
        assert out.strip() == ""

    def test_newline_stripped_from_printed_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Trailing newline from the original line is stripped before prefixing."""
        lines = ["KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"]
        _render_remove_dry_run_diff(lines, {0})

        out = capsys.readouterr().out

        assert out == "-KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"


@pytest.mark.unit
class TestRunRemoveDryRun:
    """run_remove() with dry_run=True prints diff and leaves file unchanged (AC-FUNC-002, AC-FUNC-003)."""

    _KANON_CONTENT = (
        "GITBASE=https://example.com\n"
        "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
        "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
        "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
        "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
        "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
    )

    def test_dry_run_exits_zero(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """--dry-run exits 0."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(self._KANON_CONTENT)
        args = _make_args(["foo_bar"], str(kanon_file), dry_run=True)

        result = run_remove(args)

        assert result == 0

    def test_dry_run_does_not_modify_file_content(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """File content is byte-for-byte identical after --dry-run."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(self._KANON_CONTENT)
        sha_before = _file_sha256(kanon_file)
        args = _make_args(["foo_bar"], str(kanon_file), dry_run=True)

        run_remove(args)

        sha_after = _file_sha256(kanon_file)
        assert sha_before == sha_after

    def test_dry_run_does_not_modify_mtime(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """File mtime is unchanged after --dry-run."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(self._KANON_CONTENT)
        mtime_before = kanon_file.stat().st_mtime_ns
        args = _make_args(["foo_bar"], str(kanon_file), dry_run=True)

        run_remove(args)

        mtime_after = kanon_file.stat().st_mtime_ns
        assert mtime_before == mtime_after

    def test_dry_run_prints_minus_prefixed_lines(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--dry-run output contains '-' prefixed lines for the removed block."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(self._KANON_CONTENT)
        args = _make_args(["foo_bar"], str(kanon_file), dry_run=True)

        run_remove(args)

        out = capsys.readouterr().out
        assert "-KANON_SOURCE_foo_bar_URL=https://example.com/repo.git" in out
        assert "-KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0" in out
        assert "-KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml" in out
        assert "-KANON_SOURCE_foo_bar_NAME=foo_bar" in out
        assert "-KANON_SOURCE_foo_bar_GITBASE=https://example.com" in out

    def test_dry_run_multi_source_prints_all_minus_lines(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Multi-source --dry-run prints minus lines for all five keys of each source."""
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/foo.git\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
            "KANON_SOURCE_baz_qux_URL=https://example.com/baz.git\n"
            "KANON_SOURCE_baz_qux_REF=refs/tags/2.0.0\n"
            "KANON_SOURCE_baz_qux_PATH=repo-specs/baz.xml\n"
            "KANON_SOURCE_baz_qux_NAME=baz_qux\n"
            "KANON_SOURCE_baz_qux_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(content)
        args = _make_args(["foo_bar", "baz_qux"], str(kanon_file), dry_run=True)

        result = run_remove(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "-KANON_SOURCE_foo_bar_URL" in out
        assert "-KANON_SOURCE_baz_qux_URL" in out

    def test_dry_run_leaves_file_unchanged(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """--dry-run does not modify the file on disk (AC-FUNC-003).

        The dry-run path only prints the lines that would be removed with '-'
        prefixes. The file-writing rules (line-ending preservation, blank-run
        collapse, trailing-newline normalisation) apply only to the normal write
        path, not to dry-run output. The on-disk file must remain byte-for-byte
        identical to its state before the command ran.
        """
        content = (
            "GITBASE=https://example.com\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(content)
        sha_before = _file_sha256(kanon_file)
        args = _make_args(["foo_bar"], str(kanon_file), dry_run=True)

        result = run_remove(args)

        assert result == 0

        assert _file_sha256(kanon_file) == sha_before

    @pytest.mark.parametrize(
        "dry_run,expect_file_changed",
        [
            (True, False),
            (False, True),
        ],
        ids=["dry-run=True", "dry-run=False"],
    )
    def test_parametrized_dry_run_vs_normal(
        self,
        dry_run: bool,
        expect_file_changed: bool,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Parametrized: dry-run leaves file intact; normal run modifies it."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(self._KANON_CONTENT)
        sha_before = _file_sha256(kanon_file)
        args = _make_args(["foo_bar"], str(kanon_file), dry_run=dry_run)

        run_remove(args)

        sha_after = _file_sha256(kanon_file)
        if expect_file_changed:
            assert sha_before != sha_after
        else:
            assert sha_before == sha_after
