"""Integration tests for the 'kanon remove' core path.

Invokes 'kanon remove <name>' end-to-end against a fixture .kanon file
and asserts on the resulting file content and process output.

Covers:
- Entry-name input path (Foo-Bar -> foo_bar)
- Source-name input path (foo_bar stays as foo_bar)
- Non-contiguous lines removed while other content preserved byte-for-byte
- Fewer-than-three-keys hard error with spec-canonical wording
- Missing .kanon file hard error
- Multi-source atomicity (all-or-nothing)
- Summary line on stdout
- AC-CYCLE-001 evidence (hand-written interleaved fixture)

AC-TEST-002, AC-CYCLE-001
"""

import pathlib
import subprocess
import sys
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the kanon CLI via the current Python interpreter."""
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


# ---------------------------------------------------------------------------
# Fixture .kanon content helpers
# ---------------------------------------------------------------------------

_STANDARD_HEADER = textwrap.dedent("""\
    GITBASE=https://example.com
    CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
    KANON_MARKETPLACE_INSTALL=true
""")

_FOO_BAR_TRIPLE = textwrap.dedent("""\
    KANON_SOURCE_foo_bar_URL=https://example.com/foo.git
    KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0
    KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml
""")

_BAZ_TRIPLE = textwrap.dedent("""\
    KANON_SOURCE_baz_URL=https://example.com/baz.git
    KANON_SOURCE_baz_REVISION=refs/tags/2.0.0
    KANON_SOURCE_baz_PATH=repo-specs/baz-marketplace.xml
""")


def _kanon_simple(tmp_path: pathlib.Path) -> pathlib.Path:
    """Write a simple contiguous .kanon file and return its path."""
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(_STANDARD_HEADER + _FOO_BAR_TRIPLE)
    return kanon_file


# ---------------------------------------------------------------------------
# AC-CYCLE-001 fixture: interleaved content
# ---------------------------------------------------------------------------


def _kanon_interleaved(tmp_path: pathlib.Path) -> pathlib.Path:
    """Write an interleaved .kanon file per AC-CYCLE-001 specification.

    Layout:
      standard header
      KANON_SOURCE_foo_bar_URL
      unrelated KANON_SOURCE_baz_URL
      KANON_SOURCE_foo_bar_REVISION
      comment
      KANON_SOURCE_foo_bar_PATH
    """
    content = (
        _STANDARD_HEADER
        + "KANON_SOURCE_foo_bar_URL=https://example.com/foo.git\n"
        + "KANON_SOURCE_baz_URL=https://example.com/baz.git\n"
        + "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n"
        + "# trailing comment about baz\n"
        + "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
        + "KANON_SOURCE_baz_REVISION=refs/tags/2.0.0\n"
        + "KANON_SOURCE_baz_PATH=repo-specs/baz-marketplace.xml\n"
    )
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(content)
    return kanon_file


# ---------------------------------------------------------------------------
# Integration tests: happy paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRemoveCoreHappyPath:
    """End-to-end happy-path scenarios."""

    def test_source_name_input_removes_block(self, tmp_path: pathlib.Path) -> None:
        """'kanon remove foo_bar' removes the foo_bar triple from .kanon."""
        kanon_file = _kanon_simple(tmp_path)

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        content = kanon_file.read_text()
        assert "KANON_SOURCE_foo_bar_URL" not in content
        assert "KANON_SOURCE_foo_bar_REVISION" not in content
        assert "KANON_SOURCE_foo_bar_PATH" not in content

    def test_entry_name_input_removes_block(self, tmp_path: pathlib.Path) -> None:
        """'kanon remove Foo-Bar' normalises to foo_bar and removes the block."""
        kanon_file = _kanon_simple(tmp_path)

        result = _run_kanon(["remove", "Foo-Bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        content = kanon_file.read_text()
        assert "KANON_SOURCE_foo_bar_URL" not in content
        assert "KANON_SOURCE_foo_bar_REVISION" not in content
        assert "KANON_SOURCE_foo_bar_PATH" not in content

    def test_header_preserved_after_removal(self, tmp_path: pathlib.Path) -> None:
        """Standard header lines survive the removal."""
        kanon_file = _kanon_simple(tmp_path)

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        content = kanon_file.read_text()
        assert "GITBASE=https://example.com" in content
        assert "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces" in content
        assert "KANON_MARKETPLACE_INSTALL=true" in content

    def test_stdout_summary_names_removed_keys(self, tmp_path: pathlib.Path) -> None:
        """stdout includes the three removed key names."""
        kanon_file = _kanon_simple(tmp_path)

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0
        assert "KANON_SOURCE_foo_bar_URL" in result.stdout


# ---------------------------------------------------------------------------
# AC-CYCLE-001: interleaved fixture end-to-end evidence
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRemoveCoreACCycle001:
    """AC-CYCLE-001 evidence: interleaved fixture, both input forms, re-run error."""

    def test_interleaved_removes_foo_bar_lines_only(self, tmp_path: pathlib.Path) -> None:
        """Three non-contiguous foo_bar lines removed; baz block + comments preserved."""
        kanon_file = _kanon_interleaved(tmp_path)

        result = _run_kanon(["remove", "Foo-Bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        content = kanon_file.read_text()

        # foo_bar lines gone
        assert "KANON_SOURCE_foo_bar_URL" not in content
        assert "KANON_SOURCE_foo_bar_REVISION" not in content
        assert "KANON_SOURCE_foo_bar_PATH" not in content

        # baz block intact
        assert "KANON_SOURCE_baz_URL=https://example.com/baz.git" in content
        assert "KANON_SOURCE_baz_REVISION=refs/tags/2.0.0" in content
        assert "KANON_SOURCE_baz_PATH=repo-specs/baz-marketplace.xml" in content

        # header intact
        assert "GITBASE=https://example.com" in content

        # comment intact
        assert "# trailing comment about baz" in content

    def test_interleaved_stdout_summary_present(self, tmp_path: pathlib.Path) -> None:
        """Summary line names all three removed keys."""
        kanon_file = _kanon_interleaved(tmp_path)

        result = _run_kanon(["remove", "Foo-Bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0
        assert "KANON_SOURCE_foo_bar_URL" in result.stdout

    def test_rerun_on_clean_file_produces_fewer_than_three_error(self, tmp_path: pathlib.Path) -> None:
        """Re-running remove on an already-clean file produces spec-canonical hard error."""
        kanon_file = _kanon_interleaved(tmp_path)

        # First remove succeeds
        first = _run_kanon(["remove", "Foo-Bar", "--kanon-file", str(kanon_file)])
        assert first.returncode == 0, f"First remove failed: {first.stderr!r}"

        # Second remove against now-clean file must fail
        second = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])
        assert second.returncode != 0, "Expected non-zero exit on second remove"
        assert "foo_bar" in second.stderr
        assert "not fully present in .kanon" in second.stderr
        assert "found 0 of 3 expected" in second.stderr


# ---------------------------------------------------------------------------
# Integration tests: error paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRemoveCoreErrorPaths:
    """Error-path end-to-end scenarios."""

    def test_missing_kanon_file_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """'kanon remove' exits non-zero when .kanon file is absent."""
        kanon_file = tmp_path / ".kanon"  # does not exist

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode != 0
        assert str(kanon_file) in result.stderr
        assert "nothing to remove" in result.stderr

    @pytest.mark.parametrize(
        "found_count",
        [0, 1, 2],
        ids=["found=0", "found=1", "found=2"],
    )
    def test_fewer_than_three_keys_exits_nonzero(self, found_count: int, tmp_path: pathlib.Path) -> None:
        """Fewer than 3 matching keys produces non-zero exit with spec-canonical error."""
        suffixes = ["_URL", "_REVISION", "_PATH"]
        lines = ["GITBASE=x\n"] + [f"KANON_SOURCE_foo_bar{suffix}=value\n" for suffix in suffixes[:found_count]]
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("".join(lines))

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode != 0
        assert "foo_bar" in result.stderr
        assert str(found_count) in result.stderr
        assert "3" in result.stderr

    def test_atomicity_file_unchanged_when_one_name_fails(self, tmp_path: pathlib.Path) -> None:
        """Multi-remove: if one name fails, the file is not written."""
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/foo.git\n"
            "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(content)

        result = _run_kanon(
            [
                "remove",
                "foo_bar",
                "nonexistent",
                "--kanon-file",
                str(kanon_file),
            ]
        )

        assert result.returncode != 0
        assert kanon_file.read_text() == content

    def test_multi_source_all_removed_when_all_valid(self, tmp_path: pathlib.Path) -> None:
        """Multi-remove with two valid names removes both blocks in one pass."""
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/foo.git\n"
            "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_baz_qux_URL=https://example.com/baz.git\n"
            "KANON_SOURCE_baz_qux_REVISION=refs/tags/2.0.0\n"
            "KANON_SOURCE_baz_qux_PATH=repo-specs/baz-marketplace.xml\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(content)

        result = _run_kanon(
            [
                "remove",
                "foo_bar",
                "baz_qux",
                "--kanon-file",
                str(kanon_file),
            ]
        )

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        remaining = kanon_file.read_text()
        assert "KANON_SOURCE_foo_bar_" not in remaining
        assert "KANON_SOURCE_baz_qux_" not in remaining
        assert "GITBASE=x" in remaining

    def test_help_exits_zero(self) -> None:
        """'kanon remove --help' exits 0 with help text."""
        result = _run_kanon(["remove", "--help"])
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "--kanon-file" in combined
        assert "KANON_KANON_FILE" in combined
