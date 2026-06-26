"""Integration tests for the 'kanon remove' core path.

Invokes 'kanon remove <name>' end-to-end against a fixture .kanon file
and asserts on the resulting file content and process output.

Covers:
- Entry-name input path (Foo-Bar -> foo_bar)
- Source-name input path (foo_bar stays as foo_bar)
- Non-contiguous lines removed while other content preserved byte-for-byte
- Fewer-than-structural-keys hard error with spec-canonical wording
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


_STANDARD_HEADER = textwrap.dedent("""\
    GITBASE=https://example.com
    OTHER_VAR=kept
""")

_FOO_BAR_BLOCK = textwrap.dedent("""\
    KANON_SOURCE_foo_bar_URL=https://example.com/foo.git
    KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0
    KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml
    KANON_SOURCE_foo_bar_NAME=foo_bar
    KANON_SOURCE_foo_bar_GITBASE=https://example.com
""")


def _kanon_simple(tmp_path: pathlib.Path) -> pathlib.Path:
    """Write a simple contiguous .kanon file and return its path."""
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(_STANDARD_HEADER + _FOO_BAR_BLOCK)
    return kanon_file


def _kanon_interleaved(tmp_path: pathlib.Path) -> pathlib.Path:
    """Write an interleaved .kanon file per AC-CYCLE-001 specification.

    Layout:
      standard header
      KANON_SOURCE_foo_bar_URL
      unrelated KANON_SOURCE_baz_URL
      KANON_SOURCE_foo_bar_REF
      comment
      KANON_SOURCE_foo_bar_PATH
      remaining foo_bar + baz block keys
    """
    content = (
        _STANDARD_HEADER
        + "KANON_SOURCE_foo_bar_URL=https://example.com/foo.git\n"
        + "KANON_SOURCE_baz_URL=https://example.com/baz.git\n"
        + "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
        + "# trailing comment about baz\n"
        + "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
        + "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
        + "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
        + "KANON_SOURCE_baz_REF=refs/tags/2.0.0\n"
        + "KANON_SOURCE_baz_PATH=repo-specs/baz-marketplace.xml\n"
        + "KANON_SOURCE_baz_NAME=baz\n"
        + "KANON_SOURCE_baz_GITBASE=https://example.com\n"
    )
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(content)
    return kanon_file


@pytest.mark.integration
class TestRemoveCoreHappyPath:
    """End-to-end happy-path scenarios."""

    def test_source_name_input_removes_block(self, tmp_path: pathlib.Path) -> None:
        """'kanon remove foo_bar' removes the foo_bar block from .kanon."""
        kanon_file = _kanon_simple(tmp_path)

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        content = kanon_file.read_text()
        assert "KANON_SOURCE_foo_bar_URL" not in content
        assert "KANON_SOURCE_foo_bar_REF" not in content
        assert "KANON_SOURCE_foo_bar_PATH" not in content
        assert "KANON_SOURCE_foo_bar_NAME" not in content
        assert "KANON_SOURCE_foo_bar_GITBASE" not in content

    def test_entry_name_input_removes_block(self, tmp_path: pathlib.Path) -> None:
        """'kanon remove Foo-Bar' normalises to foo_bar and removes the block."""
        kanon_file = _kanon_simple(tmp_path)

        result = _run_kanon(["remove", "Foo-Bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        content = kanon_file.read_text()
        assert "KANON_SOURCE_foo_bar_URL" not in content
        assert "KANON_SOURCE_foo_bar_REF" not in content
        assert "KANON_SOURCE_foo_bar_PATH" not in content
        assert "KANON_SOURCE_foo_bar_NAME" not in content
        assert "KANON_SOURCE_foo_bar_GITBASE" not in content

    def test_header_preserved_after_removal(self, tmp_path: pathlib.Path) -> None:
        """Non-source config lines survive removal; no marketplace header is left behind.

        ``foo_bar`` is a plain (non-marketplace) source: the fixture carries no
        ``KANON_SOURCE_<alias>_MARKETPLACE=true`` flag, so the auto-managed
        ``CLAUDE_MARKETPLACES_DIR`` header is never present and ``kanon remove``
        leaves the remaining ``GITBASE`` / ``OTHER_VAR`` config lines intact.
        """
        kanon_file = _kanon_simple(tmp_path)

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        content = kanon_file.read_text()
        assert "GITBASE=https://example.com" in content
        assert "OTHER_VAR=kept" in content
        assert "CLAUDE_MARKETPLACES_DIR" not in content

    def test_stdout_summary_names_removed_keys(self, tmp_path: pathlib.Path) -> None:
        """stdout names the four structural removed keys; the optional _GITBASE
        env-var line is still removed from the file even though the summary names
        only the structural keys.
        """
        kanon_file = _kanon_simple(tmp_path)

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0
        assert "KANON_SOURCE_foo_bar_URL" in result.stdout
        assert "KANON_SOURCE_foo_bar_REF" in result.stdout
        assert "KANON_SOURCE_foo_bar_PATH" in result.stdout
        assert "KANON_SOURCE_foo_bar_NAME" in result.stdout
        assert "KANON_SOURCE_foo_bar_GITBASE" not in kanon_file.read_text(), (
            "the optional _GITBASE env-var line must be removed along with the structural block"
        )


@pytest.mark.integration
class TestRemoveCoreACCycle001:
    """AC-CYCLE-001 evidence: interleaved fixture, both input forms, re-run error."""

    def test_interleaved_removes_foo_bar_lines_only(self, tmp_path: pathlib.Path) -> None:
        """Five non-contiguous foo_bar lines removed; baz block + comments preserved."""
        kanon_file = _kanon_interleaved(tmp_path)

        result = _run_kanon(["remove", "Foo-Bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        content = kanon_file.read_text()

        assert "KANON_SOURCE_foo_bar_URL" not in content
        assert "KANON_SOURCE_foo_bar_REF" not in content
        assert "KANON_SOURCE_foo_bar_PATH" not in content
        assert "KANON_SOURCE_foo_bar_NAME" not in content
        assert "KANON_SOURCE_foo_bar_GITBASE" not in content

        assert "KANON_SOURCE_baz_URL=https://example.com/baz.git" in content
        assert "KANON_SOURCE_baz_REF=refs/tags/2.0.0" in content
        assert "KANON_SOURCE_baz_PATH=repo-specs/baz-marketplace.xml" in content
        assert "KANON_SOURCE_baz_NAME=baz" in content
        assert "KANON_SOURCE_baz_GITBASE=https://example.com" in content

        assert "GITBASE=https://example.com" in content

        assert "# trailing comment about baz" in content

    def test_interleaved_stdout_summary_present(self, tmp_path: pathlib.Path) -> None:
        """Summary line names the four structural removed keys."""
        kanon_file = _kanon_interleaved(tmp_path)

        result = _run_kanon(["remove", "Foo-Bar", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0
        assert "KANON_SOURCE_foo_bar_URL" in result.stdout
        assert "KANON_SOURCE_foo_bar_REF" in result.stdout
        assert "KANON_SOURCE_foo_bar_PATH" in result.stdout
        assert "KANON_SOURCE_foo_bar_NAME" in result.stdout

    def test_rerun_on_clean_file_produces_fewer_than_structural_error(self, tmp_path: pathlib.Path) -> None:
        """Re-running remove on an already-clean file produces spec-canonical hard error."""
        kanon_file = _kanon_interleaved(tmp_path)

        first = _run_kanon(["remove", "Foo-Bar", "--kanon-file", str(kanon_file)])
        assert first.returncode == 0, f"First remove failed: {first.stderr!r}"

        second = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])
        assert second.returncode != 0, "Expected non-zero exit on second remove"
        assert "foo_bar" in second.stderr
        assert "not fully present in .kanon" in second.stderr
        assert "found 0 of 4 expected" in second.stderr


@pytest.mark.integration
class TestRemoveCoreErrorPaths:
    """Error-path end-to-end scenarios."""

    def test_missing_kanon_file_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """'kanon remove' exits non-zero when .kanon file is absent."""
        kanon_file = tmp_path / ".kanon"

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode != 0
        assert str(kanon_file) in result.stderr
        assert "nothing to remove" in result.stderr

    @pytest.mark.parametrize(
        "found_count",
        [0, 1, 2, 3],
        ids=["found=0", "found=1", "found=2", "found=3"],
    )
    def test_fewer_than_structural_keys_exits_nonzero(self, found_count: int, tmp_path: pathlib.Path) -> None:
        """Fewer than the 4 structural keys produces non-zero exit with spec-canonical error."""
        suffixes = ["_URL", "_REF", "_PATH", "_NAME"]
        lines = ["GITBASE=x\n"] + [f"KANON_SOURCE_foo_bar{suffix}=value\n" for suffix in suffixes[:found_count]]
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("".join(lines))

        result = _run_kanon(["remove", "foo_bar", "--kanon-file", str(kanon_file)])

        assert result.returncode != 0
        assert "foo_bar" in result.stderr
        assert f"found {found_count} of 4 expected" in result.stderr

    def test_atomicity_file_unchanged_when_one_name_fails(self, tmp_path: pathlib.Path) -> None:
        """Multi-remove: if one name fails, the file is not written."""
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/foo.git\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
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
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
            "KANON_SOURCE_baz_qux_URL=https://example.com/baz.git\n"
            "KANON_SOURCE_baz_qux_REF=refs/tags/2.0.0\n"
            "KANON_SOURCE_baz_qux_PATH=repo-specs/baz-marketplace.xml\n"
            "KANON_SOURCE_baz_qux_NAME=baz_qux\n"
            "KANON_SOURCE_baz_qux_GITBASE=https://example.com\n"
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


_MARKETPLACES_DIR_HEADER = "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces"


def _marketplace_block(alias: str) -> str:
    """Return the .kanon block for one marketplace-flagged source alias.

    Args:
        alias: The canonical source alias.

    Returns:
        The block text (trailing newline) including the ``_MARKETPLACE=true`` flag.
    """
    return (
        f"KANON_SOURCE_{alias}_URL=https://example.com/{alias}.git\n"
        f"KANON_SOURCE_{alias}_REF=refs/tags/1.0.0\n"
        f"KANON_SOURCE_{alias}_PATH=repo-specs/{alias}-marketplace.xml\n"
        f"KANON_SOURCE_{alias}_NAME={alias}\n"
        f"KANON_SOURCE_{alias}_MARKETPLACE=true\n"
    )


@pytest.mark.integration
class TestRemovePrunesMarketplacesDirHeader:
    """remove of the last marketplace dependency prunes the auto-managed header (Feature A)."""

    def test_remove_last_marketplace_prunes_header(self, tmp_path: pathlib.Path) -> None:
        """Removing the only marketplace source drops the CLAUDE_MARKETPLACES_DIR header."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(_MARKETPLACES_DIR_HEADER + "\n" + _marketplace_block("only_mp"))

        result = _run_kanon(["remove", "only_mp", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        content = kanon_file.read_text()
        assert "KANON_SOURCE_only_mp_" not in content
        assert "CLAUDE_MARKETPLACES_DIR" not in content, (
            "the header must be pruned once the last _MARKETPLACE=true dependency is removed"
        )

    def test_remove_one_of_two_marketplaces_keeps_header(self, tmp_path: pathlib.Path) -> None:
        """Removing one of two marketplace sources keeps the header (one remains)."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            _MARKETPLACES_DIR_HEADER + "\n" + _marketplace_block("first_mp") + _marketplace_block("second_mp")
        )

        result = _run_kanon(["remove", "first_mp", "--kanon-file", str(kanon_file)])

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        content = kanon_file.read_text()
        assert "KANON_SOURCE_first_mp_" not in content
        assert "KANON_SOURCE_second_mp_MARKETPLACE=true" in content
        assert content.count("CLAUDE_MARKETPLACES_DIR") == 1, (
            "the header must remain while a _MARKETPLACE=true dependency still exists"
        )

    def test_remove_keeps_cwd_clean_no_kanon_data(self, tmp_path: pathlib.Path) -> None:
        """remove serialises under KANON_HOME, leaving no .kanon-data in the project CWD (Feature B)."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(_MARKETPLACES_DIR_HEADER + "\n" + _marketplace_block("only_mp"))

        result = _run_kanon(["remove", "only_mp", "--kanon-file", str(kanon_file)], cwd=workspace)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert not (workspace / ".kanon-data").exists(), (
            "kanon remove must not create a .kanon-data lock dir in the project CWD"
        )
        assert kanon_file.exists()
