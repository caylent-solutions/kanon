"""Unit tests for the 'kanon remove' subcommand.

Covers:
- Entry-name vs source-name input paths (AC-FUNC-004)
- Non-contiguous three-lines scanner (AC-FUNC-005)
- Fewer-than-three-keys hard error (AC-FUNC-006, parameterised)
- Missing .kanon hard error (AC-FUNC-007)
- Multi-source atomicity rule (AC-FUNC-008)
- Summary line output (AC-FUNC-009)

AC-TEST-001
"""

import argparse
import pathlib
import textwrap

import pytest

from kanon_cli.commands.remove import (
    _collect_removal_lines,
    _scan_source_lines,
    register,
    run_remove,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _write_kanon(path: pathlib.Path, content: str) -> None:
    """Write text content to the given path."""
    path.write_text(content)


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterSubparser:
    """register() adds a 'remove' subparser with the required arguments (AC-FUNC-001, AC-FUNC-003)."""

    def test_register_creates_remove_subparser(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["remove", "foo_bar"])
        assert args.command == "remove"

    def test_positional_names_one_value(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["remove", "foo_bar"])
        assert args.names == ["foo_bar"]

    def test_positional_names_multiple_values(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["remove", "foo_bar", "baz_qux"])
        assert args.names == ["foo_bar", "baz_qux"]

    def test_kanon_file_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KANON_KANON_FILE", raising=False)
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["remove", "foo_bar"])
        assert args.kanon_file == "./.kanon"

    def test_kanon_file_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KANON_KANON_FILE", "/tmp/mykanon")
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["remove", "foo_bar"])
        assert args.kanon_file == "/tmp/mykanon"

    def test_kanon_file_cli_flag_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KANON_KANON_FILE", "/tmp/mykanon")
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["remove", "foo_bar", "--kanon-file", "/other/.kanon"])
        assert args.kanon_file == "/other/.kanon"

    def test_force_flag_default_false(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["remove", "foo_bar"])
        assert args.force is False

    def test_force_flag_set(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["remove", "foo_bar", "--force"])
        assert args.force is True

    def test_dry_run_flag_default_false(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["remove", "foo_bar"])
        assert args.dry_run is False

    def test_dry_run_flag_set(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["remove", "foo_bar", "--dry-run"])
        assert args.dry_run is True

    def test_no_color_flag_default_false(self) -> None:
        """--no-color defaults to False; the flag is provided by the root parser global flags."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["remove", "foo_bar"])
        assert args.no_color is False

    def test_no_color_flag_set(self) -> None:
        """--no-color is accessible for 'remove' via the root parser global flags."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["--no-color", "remove", "foo_bar"])
        assert args.no_color is True

    def test_sets_func_to_run_remove(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["remove", "foo_bar"])
        assert args.func is run_remove


# ---------------------------------------------------------------------------
# _scan_source_lines helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScanSourceLines:
    """_scan_source_lines() returns line indices matching KANON_SOURCE_<name>_* keys."""

    def test_finds_all_three_contiguous(self) -> None:
        lines = [
            "GITBASE=x\n",
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n",
            "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n",
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n",
        ]
        result = _scan_source_lines(lines, "foo_bar")
        assert result == {1, 2, 3}

    def test_finds_all_three_non_contiguous(self) -> None:
        lines = [
            "GITBASE=x\n",
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n",
            "# comment interleaved\n",
            "KANON_SOURCE_baz_URL=https://other.com/repo.git\n",
            "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n",
            "# another comment\n",
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n",
        ]
        result = _scan_source_lines(lines, "foo_bar")
        assert result == {1, 4, 6}

    def test_returns_empty_set_when_none_found(self) -> None:
        lines = [
            "GITBASE=x\n",
            "KANON_SOURCE_baz_URL=https://other.com/repo.git\n",
        ]
        result = _scan_source_lines(lines, "foo_bar")
        assert result == set()

    def test_finds_only_one_key(self) -> None:
        lines = [
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n",
            "KANON_SOURCE_baz_URL=https://other.com/repo.git\n",
        ]
        result = _scan_source_lines(lines, "foo_bar")
        assert result == {0}

    def test_does_not_match_partial_name(self) -> None:
        """KANON_SOURCE_foo_bar_URL must not match KANON_SOURCE_foo_barz_URL."""
        lines = [
            "KANON_SOURCE_foo_barz_URL=https://example.com\n",
            "KANON_SOURCE_foo_bar_URL=https://actual.com\n",
        ]
        result = _scan_source_lines(lines, "foo_bar")
        assert result == {1}

    def test_ignores_comment_lines(self) -> None:
        lines = [
            "# KANON_SOURCE_foo_bar_URL=commented-out\n",
            "KANON_SOURCE_foo_bar_URL=https://example.com\n",
            "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n",
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n",
        ]
        result = _scan_source_lines(lines, "foo_bar")
        # Comment line (index 0) should NOT be included
        assert result == {1, 2, 3}


# ---------------------------------------------------------------------------
# _collect_removal_lines helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCollectRemovalLines:
    """_collect_removal_lines() validates count and returns indices to remove."""

    def test_returns_three_indices_happy_path(self) -> None:
        lines = [
            "GITBASE=x\n",
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n",
            "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n",
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n",
        ]
        result = _collect_removal_lines(lines, "foo_bar", "Foo-Bar")
        assert result == {1, 2, 3}

    @pytest.mark.parametrize(
        "found_count",
        [0, 1, 2],
        ids=["found=0", "found=1", "found=2"],
    )
    def test_raises_system_exit_on_fewer_than_three(
        self, found_count: int, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Fewer than 3 matching keys is a hard error with spec-canonical message."""
        key_suffixes = ["_URL", "_REVISION", "_PATH"]
        lines = [f"KANON_SOURCE_foo_bar{suffix}=value\n" for suffix in key_suffixes[:found_count]]
        lines.insert(0, "GITBASE=x\n")

        with pytest.raises(SystemExit) as exc_info:
            _collect_removal_lines(lines, "foo_bar", "Foo-Bar")

        assert exc_info.value.code != 0
        stderr = capsys.readouterr().err
        assert "Foo-Bar" in stderr
        assert "foo_bar" in stderr
        assert str(found_count) in stderr
        assert "3" in stderr

    def test_error_message_contains_spec_canonical_wording(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The error message follows the spec-canonical wording."""
        lines = ["KANON_SOURCE_foo_bar_URL=https://example.com\n"]

        with pytest.raises(SystemExit):
            _collect_removal_lines(lines, "foo_bar", "Foo-Bar")

        stderr = capsys.readouterr().err
        # Spec-canonical: "not fully present in .kanon; found <n> of 3 expected"
        assert "not fully present in .kanon" in stderr
        assert "found 1 of 3 expected" in stderr
        assert "KANON_SOURCE_foo_bar_" in stderr


# ---------------------------------------------------------------------------
# run_remove -- missing .kanon file
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunRemoveMissingFile:
    """run_remove() hard-errors when the .kanon file does not exist (AC-FUNC-007)."""

    def test_exits_nonzero_when_kanon_file_missing(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        kanon_file = tmp_path / ".kanon"
        args = _make_args(["foo_bar"], str(kanon_file))

        with pytest.raises(SystemExit) as exc_info:
            run_remove(args)

        assert exc_info.value.code != 0

    def test_error_message_names_path(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        kanon_file = tmp_path / ".kanon"
        args = _make_args(["foo_bar"], str(kanon_file))

        with pytest.raises(SystemExit):
            run_remove(args)

        stderr = capsys.readouterr().err
        assert str(kanon_file) in stderr
        assert "nothing to remove" in stderr


# ---------------------------------------------------------------------------
# run_remove -- entry-name vs source-name input paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunRemoveInputPaths:
    """Both entry-name (Foo-Bar) and source-name (foo_bar) inputs produce identical results (AC-FUNC-004)."""

    _KANON_CONTENT = textwrap.dedent("""\
        GITBASE=https://example.com
        CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
        KANON_MARKETPLACE_INSTALL=true
        KANON_SOURCE_foo_bar_URL=https://example.com/repo.git
        KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0
        KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml
    """)

    _EXPECTED_AFTER_REMOVAL = textwrap.dedent("""\
        GITBASE=https://example.com
        CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
        KANON_MARKETPLACE_INSTALL=true
    """)

    def test_entry_name_input_removes_block(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Input 'Foo-Bar' normalises to 'foo_bar' and removes the block."""
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, self._KANON_CONTENT)
        args = _make_args(["Foo-Bar"], str(kanon_file))

        exit_code = run_remove(args)

        assert exit_code == 0
        result = kanon_file.read_text()
        assert "KANON_SOURCE_foo_bar_URL" not in result
        assert "KANON_SOURCE_foo_bar_REVISION" not in result
        assert "KANON_SOURCE_foo_bar_PATH" not in result

    def test_source_name_input_removes_block(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Input 'foo_bar' stays as 'foo_bar' and removes the block."""
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, self._KANON_CONTENT)
        args = _make_args(["foo_bar"], str(kanon_file))

        exit_code = run_remove(args)

        assert exit_code == 0
        result = kanon_file.read_text()
        assert "KANON_SOURCE_foo_bar_URL" not in result
        assert "KANON_SOURCE_foo_bar_REVISION" not in result
        assert "KANON_SOURCE_foo_bar_PATH" not in result

    def test_entry_name_and_source_name_produce_same_result(self, tmp_path: pathlib.Path) -> None:
        """Both 'Foo-Bar' and 'foo_bar' produce identical output files."""
        kanon_a = tmp_path / ".kanon_a"
        kanon_b = tmp_path / ".kanon_b"
        _write_kanon(kanon_a, self._KANON_CONTENT)
        _write_kanon(kanon_b, self._KANON_CONTENT)

        run_remove(_make_args(["Foo-Bar"], str(kanon_a)))
        run_remove(_make_args(["foo_bar"], str(kanon_b)))

        assert kanon_a.read_text() == kanon_b.read_text()

    def test_other_content_preserved_byte_for_byte(self, tmp_path: pathlib.Path) -> None:
        """Non-removed lines are preserved byte-for-byte."""
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, self._KANON_CONTENT)
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        result = kanon_file.read_text()
        assert "GITBASE=https://example.com" in result
        assert "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces" in result
        assert "KANON_MARKETPLACE_INSTALL=true" in result


# ---------------------------------------------------------------------------
# run_remove -- non-contiguous lines
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunRemoveNonContiguous:
    """Scanner finds and removes three lines even when non-contiguous (AC-FUNC-005)."""

    def test_removes_non_contiguous_triple(self, tmp_path: pathlib.Path) -> None:
        content = textwrap.dedent("""\
            GITBASE=https://example.com
            KANON_SOURCE_foo_bar_URL=https://example.com/repo.git
            # interleaved comment
            KANON_SOURCE_baz_URL=https://other.com/baz.git
            KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0
            # another comment
            KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml
        """)
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, content)
        args = _make_args(["foo_bar"], str(kanon_file))

        exit_code = run_remove(args)

        assert exit_code == 0
        result = kanon_file.read_text()
        # foo_bar keys removed
        assert "KANON_SOURCE_foo_bar_URL" not in result
        assert "KANON_SOURCE_foo_bar_REVISION" not in result
        assert "KANON_SOURCE_foo_bar_PATH" not in result
        # Other content preserved
        assert "GITBASE=https://example.com" in result
        assert "# interleaved comment" in result
        assert "KANON_SOURCE_baz_URL=https://other.com/baz.git" in result
        assert "# another comment" in result

    def test_preserves_byte_order_of_remaining_lines(self, tmp_path: pathlib.Path) -> None:
        """Non-removed lines retain their original byte order."""
        content = (
            "LINE_A=1\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
            "LINE_B=2\n"
            "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n"
            "LINE_C=3\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "LINE_D=4\n"
        )
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, content)
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        result = kanon_file.read_text()
        lines = [ln for ln in result.splitlines() if ln.strip()]
        assert lines == ["LINE_A=1", "LINE_B=2", "LINE_C=3", "LINE_D=4"]


# ---------------------------------------------------------------------------
# run_remove -- fewer-than-three-keys hard error (AC-FUNC-006)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunRemoveFewerThanThreeKeys:
    """Missing keys produce a spec-canonical hard error; file is NOT modified (AC-FUNC-006)."""

    @pytest.mark.parametrize(
        "found_count",
        [0, 1, 2],
        ids=["found=0", "found=1", "found=2"],
    )
    def test_exits_nonzero_with_n_keys(
        self,
        found_count: int,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        suffixes = ["_URL", "_REVISION", "_PATH"]
        lines = ["GITBASE=x\n"]
        for suffix in suffixes[:found_count]:
            lines.append(f"KANON_SOURCE_foo_bar{suffix}=value\n")

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("".join(lines))
        args = _make_args(["foo_bar"], str(kanon_file))

        with pytest.raises(SystemExit) as exc_info:
            run_remove(args)

        assert exc_info.value.code != 0
        stderr = capsys.readouterr().err
        assert "foo_bar" in stderr
        assert str(found_count) in stderr
        assert "3" in stderr

    @pytest.mark.parametrize(
        "found_count",
        [0, 1, 2],
        ids=["found=0", "found=1", "found=2"],
    )
    def test_file_not_modified_on_error(
        self,
        found_count: int,
        tmp_path: pathlib.Path,
    ) -> None:
        suffixes = ["_URL", "_REVISION", "_PATH"]
        lines = ["GITBASE=x\n"]
        for suffix in suffixes[:found_count]:
            lines.append(f"KANON_SOURCE_foo_bar{suffix}=value\n")
        original = "".join(lines)

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(original)
        args = _make_args(["foo_bar"], str(kanon_file))

        with pytest.raises(SystemExit):
            run_remove(args)

        assert kanon_file.read_text() == original


# ---------------------------------------------------------------------------
# run_remove -- summary line output (AC-FUNC-009)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunRemoveSummaryOutput:
    """run_remove() writes one summary line to stdout per removed source (AC-FUNC-009)."""

    def test_summary_line_mentions_three_keys(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
        )
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, content)
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        stdout = capsys.readouterr().out
        assert "KANON_SOURCE_foo_bar_URL" in stdout
        assert "KANON_SOURCE_foo_bar_REVISION" in stdout or "_REVISION" in stdout
        assert "KANON_SOURCE_foo_bar_PATH" in stdout or "_PATH" in stdout

    def test_summary_mentions_kanon_file_path(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
        )
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, content)
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        stdout = capsys.readouterr().out
        assert str(kanon_file) in stdout

    def test_two_sources_two_summary_lines(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
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
        _write_kanon(kanon_file, content)
        args = _make_args(["foo_bar", "baz_qux"], str(kanon_file))

        run_remove(args)

        stdout = capsys.readouterr().out
        assert "foo_bar" in stdout
        assert "baz_qux" in stdout


# ---------------------------------------------------------------------------
# run_remove -- multi-source atomicity (AC-FUNC-008)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunRemoveAtomicity:
    """All-or-nothing semantics: if any name fails, the file is NOT written (AC-FUNC-008)."""

    def test_no_write_if_any_name_fails(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """When one of two names fails validation, neither block is removed."""
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/foo.git\n"
            "KANON_SOURCE_foo_bar_REVISION=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
        )
        original = content
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, content)
        # "foo_bar" is valid (3 keys), "nonexistent" has 0 keys
        args = _make_args(["foo_bar", "nonexistent"], str(kanon_file))

        with pytest.raises(SystemExit) as exc_info:
            run_remove(args)

        assert exc_info.value.code != 0
        # File unchanged
        assert kanon_file.read_text() == original

    def test_all_blocks_removed_when_all_valid(self, tmp_path: pathlib.Path) -> None:
        """All blocks are removed when every requested name is fully present."""
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
        _write_kanon(kanon_file, content)
        args = _make_args(["foo_bar", "baz_qux"], str(kanon_file))

        exit_code = run_remove(args)

        assert exit_code == 0
        result = kanon_file.read_text()
        assert "KANON_SOURCE_foo_bar_" not in result
        assert "KANON_SOURCE_baz_qux_" not in result
        assert "GITBASE=x" in result
