"""Unit tests for the 'kanon remove' subcommand.

Covers:
- Entry-name vs source-name input paths (AC-FUNC-004)
- Non-contiguous block scanner (AC-FUNC-005)
- Fewer-than-expected-keys hard error (AC-FUNC-006, parameterised)
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

    def test_remove_short_dash_h_exits_0(self) -> None:
        """kanon remove -h exits 0 (add_help=True on the remove subparser)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["remove", "-h"])
        assert exc_info.value.code == 0

    def test_remove_subparser_has_add_help_true(self) -> None:
        """The 'remove' subparser has add_help=True set explicitly."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        remove_parser = subparsers.choices["remove"]
        assert remove_parser.add_help is True, "remove subparser must have add_help=True so '-h' is accepted"


@pytest.mark.unit
class TestScanSourceLines:
    """_scan_source_lines() returns line indices matching KANON_SOURCE_<name>_* keys."""

    def test_finds_all_five_contiguous(self) -> None:
        lines = [
            "GITBASE=x\n",
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n",
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n",
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n",
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n",
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n",
        ]
        result = _scan_source_lines(lines, "foo_bar")
        assert result == {1, 2, 3, 4, 5}

    def test_finds_all_five_non_contiguous(self) -> None:
        lines = [
            "GITBASE=x\n",
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n",
            "# comment interleaved\n",
            "KANON_SOURCE_baz_URL=https://other.com/repo.git\n",
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n",
            "# another comment\n",
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n",
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n",
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n",
        ]
        result = _scan_source_lines(lines, "foo_bar")
        assert result == {1, 4, 6, 7, 8}

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
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n",
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n",
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n",
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n",
        ]
        result = _scan_source_lines(lines, "foo_bar")

        assert result == {1, 2, 3, 4, 5}


@pytest.mark.unit
class TestCollectRemovalLines:
    """_collect_removal_lines() validates count and returns indices to remove."""

    def test_returns_five_indices_happy_path(self) -> None:
        lines = [
            "GITBASE=x\n",
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n",
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n",
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n",
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n",
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n",
        ]
        result = _collect_removal_lines(lines, "foo_bar", "Foo-Bar")
        assert result == {1, 2, 3, 4, 5}

    @pytest.mark.parametrize(
        "found_count",
        [0, 1, 2, 3, 4],
        ids=["found=0", "found=1", "found=2", "found=3", "found=4"],
    )
    def test_raises_system_exit_on_fewer_than_five(
        self, found_count: int, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Fewer than 5 matching keys is a hard error with spec-canonical message."""
        key_suffixes = ["_URL", "_REF", "_PATH", "_NAME", "_GITBASE"]
        lines = [f"KANON_SOURCE_foo_bar{suffix}=value\n" for suffix in key_suffixes[:found_count]]
        lines.insert(0, "GITBASE=x\n")

        with pytest.raises(SystemExit) as exc_info:
            _collect_removal_lines(lines, "foo_bar", "Foo-Bar")

        assert exc_info.value.code != 0
        stderr = capsys.readouterr().err
        assert "Foo-Bar" in stderr
        assert "foo_bar" in stderr
        assert f"found {found_count} of 5 expected" in stderr

    def test_error_message_contains_spec_canonical_wording(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The error message follows the spec-canonical wording."""
        lines = ["KANON_SOURCE_foo_bar_URL=https://example.com\n"]

        with pytest.raises(SystemExit):
            _collect_removal_lines(lines, "foo_bar", "Foo-Bar")

        stderr = capsys.readouterr().err

        assert "not fully present in .kanon" in stderr
        assert "found 1 of 5 expected" in stderr
        assert "KANON_SOURCE_foo_bar_" in stderr


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


@pytest.mark.unit
class TestRunRemoveInputPaths:
    """Both entry-name (Foo-Bar) and source-name (foo_bar) inputs produce identical results (AC-FUNC-004)."""

    _KANON_CONTENT = textwrap.dedent("""\
        GITBASE=https://example.com
        CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
        KANON_MARKETPLACE_INSTALL=true
        KANON_SOURCE_foo_bar_URL=https://example.com/repo.git
        KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0
        KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml
        KANON_SOURCE_foo_bar_NAME=foo_bar
        KANON_SOURCE_foo_bar_GITBASE=https://example.com
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
        assert "KANON_SOURCE_foo_bar_REF" not in result
        assert "KANON_SOURCE_foo_bar_PATH" not in result
        assert "KANON_SOURCE_foo_bar_NAME" not in result
        assert "KANON_SOURCE_foo_bar_GITBASE" not in result

    def test_source_name_input_removes_block(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Input 'foo_bar' stays as 'foo_bar' and removes the block."""
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, self._KANON_CONTENT)
        args = _make_args(["foo_bar"], str(kanon_file))

        exit_code = run_remove(args)

        assert exit_code == 0
        result = kanon_file.read_text()
        assert "KANON_SOURCE_foo_bar_URL" not in result
        assert "KANON_SOURCE_foo_bar_REF" not in result
        assert "KANON_SOURCE_foo_bar_PATH" not in result
        assert "KANON_SOURCE_foo_bar_NAME" not in result
        assert "KANON_SOURCE_foo_bar_GITBASE" not in result

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


@pytest.mark.unit
class TestRunRemoveNonContiguous:
    """Scanner finds and removes the full block even when non-contiguous (AC-FUNC-005)."""

    def test_removes_non_contiguous_block(self, tmp_path: pathlib.Path) -> None:
        content = textwrap.dedent("""\
            GITBASE=https://example.com
            KANON_SOURCE_foo_bar_URL=https://example.com/repo.git
            # interleaved comment
            KANON_SOURCE_baz_URL=https://other.com/baz.git
            KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0
            # another comment
            KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml
            KANON_SOURCE_foo_bar_NAME=foo_bar
            KANON_SOURCE_foo_bar_GITBASE=https://example.com
        """)
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, content)
        args = _make_args(["foo_bar"], str(kanon_file))

        exit_code = run_remove(args)

        assert exit_code == 0
        result = kanon_file.read_text()

        assert "KANON_SOURCE_foo_bar_URL" not in result
        assert "KANON_SOURCE_foo_bar_REF" not in result
        assert "KANON_SOURCE_foo_bar_PATH" not in result
        assert "KANON_SOURCE_foo_bar_NAME" not in result
        assert "KANON_SOURCE_foo_bar_GITBASE" not in result

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
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "LINE_C=3\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "LINE_D=4\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "LINE_E=5\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
            "LINE_F=6\n"
        )
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, content)
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        result = kanon_file.read_text()
        lines = [ln for ln in result.splitlines() if ln.strip()]
        assert lines == ["LINE_A=1", "LINE_B=2", "LINE_C=3", "LINE_D=4", "LINE_E=5", "LINE_F=6"]


@pytest.mark.unit
class TestRunRemoveFewerThanExpectedKeys:
    """Missing keys produce a spec-canonical hard error; file is NOT modified (AC-FUNC-006)."""

    @pytest.mark.parametrize(
        "found_count",
        [0, 1, 2, 3, 4],
        ids=["found=0", "found=1", "found=2", "found=3", "found=4"],
    )
    def test_exits_nonzero_with_n_keys(
        self,
        found_count: int,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        suffixes = ["_URL", "_REF", "_PATH", "_NAME", "_GITBASE"]
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
        assert f"found {found_count} of 5 expected" in stderr

    @pytest.mark.parametrize(
        "found_count",
        [0, 1, 2, 3, 4],
        ids=["found=0", "found=1", "found=2", "found=3", "found=4"],
    )
    def test_file_not_modified_on_error(
        self,
        found_count: int,
        tmp_path: pathlib.Path,
    ) -> None:
        suffixes = ["_URL", "_REF", "_PATH", "_NAME", "_GITBASE"]
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


@pytest.mark.unit
class TestRunRemoveSummaryOutput:
    """run_remove() writes one summary line to stdout per removed source (AC-FUNC-009)."""

    def test_summary_line_mentions_five_keys(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, content)
        args = _make_args(["foo_bar"], str(kanon_file))

        run_remove(args)

        stdout = capsys.readouterr().out
        assert "KANON_SOURCE_foo_bar_URL" in stdout
        assert "KANON_SOURCE_foo_bar_REF" in stdout
        assert "KANON_SOURCE_foo_bar_PATH" in stdout
        assert "KANON_SOURCE_foo_bar_NAME" in stdout
        assert "KANON_SOURCE_foo_bar_GITBASE" in stdout

    def test_summary_mentions_kanon_file_path(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
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
        _write_kanon(kanon_file, content)
        args = _make_args(["foo_bar", "baz_qux"], str(kanon_file))

        run_remove(args)

        stdout = capsys.readouterr().out
        assert "foo_bar" in stdout
        assert "baz_qux" in stdout


@pytest.mark.unit
class TestRunRemoveAtomicity:
    """All-or-nothing semantics: if any name fails, the file is NOT written (AC-FUNC-008)."""

    def test_no_write_if_any_name_fails(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """When one of two names fails validation, neither block is removed."""
        content = (
            "GITBASE=x\n"
            "KANON_SOURCE_foo_bar_URL=https://example.com/foo.git\n"
            "KANON_SOURCE_foo_bar_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_foo_bar_PATH=repo-specs/foo-marketplace.xml\n"
            "KANON_SOURCE_foo_bar_NAME=foo_bar\n"
            "KANON_SOURCE_foo_bar_GITBASE=https://example.com\n"
        )
        original = content
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, content)

        args = _make_args(["foo_bar", "nonexistent"], str(kanon_file))

        with pytest.raises(SystemExit) as exc_info:
            run_remove(args)

        assert exc_info.value.code != 0

        assert kanon_file.read_text() == original

    def test_all_blocks_removed_when_all_valid(self, tmp_path: pathlib.Path) -> None:
        """All blocks are removed when every requested name is fully present."""
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
        _write_kanon(kanon_file, content)
        args = _make_args(["foo_bar", "baz_qux"], str(kanon_file))

        exit_code = run_remove(args)

        assert exit_code == 0
        result = kanon_file.read_text()
        assert "KANON_SOURCE_foo_bar_" not in result
        assert "KANON_SOURCE_baz_qux_" not in result
        assert "GITBASE=x" in result


@pytest.mark.unit
class TestRunRemoveWorkspaceLock:
    """run_remove wraps the .kanon write inside kanon_workspace_lock (AC-FUNC-005)."""

    def test_run_remove_creates_kanon_data_dir(self, tmp_path: pathlib.Path) -> None:
        """run_remove creates .kanon-data/ via workspace lock acquisition.

        The kanon_workspace_lock context manager creates .kanon-data/ eagerly;
        a normal run_remove call in a fresh workspace must create the directory
        as a side effect of acquiring the write lock.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        content = (
            "GITBASE=https://git.example.com\n"
            "KANON_SOURCE_alpha_URL=https://example.com/alpha.git\n"
            "KANON_SOURCE_alpha_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_alpha_PATH=repo-specs/alpha-marketplace.xml\n"
            "KANON_SOURCE_alpha_NAME=alpha\n"
            "KANON_SOURCE_alpha_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, content)

        assert not (tmp_path / ".kanon-data").exists()

        args = _make_args(["alpha"], str(kanon_file))
        run_remove(args)

        assert (tmp_path / ".kanon-data").is_dir(), (
            "run_remove must create .kanon-data/ via kanon_workspace_lock eager-create "
            "when the workspace has no prior .kanon-data/ directory"
        )

    def test_run_remove_dry_run_does_not_create_kanon_data_dir(self, tmp_path: pathlib.Path) -> None:
        """run_remove --dry-run does not acquire the workspace lock or create .kanon-data/.

        The lock is only acquired on the non-dry-run write path.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        content = (
            "GITBASE=https://git.example.com\n"
            "KANON_SOURCE_beta_URL=https://example.com/beta.git\n"
            "KANON_SOURCE_beta_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_beta_PATH=repo-specs/beta-marketplace.xml\n"
            "KANON_SOURCE_beta_NAME=beta\n"
            "KANON_SOURCE_beta_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        _write_kanon(kanon_file, content)

        args = _make_args(["beta"], str(kanon_file), dry_run=True)
        result = run_remove(args)

        assert result == 0

        assert not (tmp_path / ".kanon-data").exists(), (
            "run_remove --dry-run must not create .kanon-data/; "
            "the workspace lock is only acquired on the non-dry-run write path"
        )


@pytest.mark.unit
class TestRunRemoveForce:
    """--force silently skips sources not fully present; known sources are still removed (AC-FUNC-001..004)."""

    _KNOWN_CONTENT = (
        "GITBASE=https://git.example.com\n"
        "KANON_SOURCE_known_a_URL=https://example.com/known_a.git\n"
        "KANON_SOURCE_known_a_REF=refs/tags/1.0.0\n"
        "KANON_SOURCE_known_a_PATH=repo-specs/known_a.xml\n"
        "KANON_SOURCE_known_a_NAME=known_a\n"
        "KANON_SOURCE_known_a_GITBASE=https://example.com\n"
    )

    def test_force_unknown_only_exits_0(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """AC-FUNC-001: remove unknown --force exits 0; file is byte-for-byte unchanged."""
        kanon_file = tmp_path / ".kanon"
        original = self._KNOWN_CONTENT
        kanon_file.write_text(original)
        args = _make_args(["unknown_source"], str(kanon_file), force=True)

        result = run_remove(args)

        assert result == 0
        assert kanon_file.read_text() == original

    def test_force_unknown_only_file_unchanged(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001: file content is byte-for-byte unchanged when the only requested source is absent."""
        kanon_file = tmp_path / ".kanon"
        original = self._KNOWN_CONTENT
        kanon_file.write_text(original)
        args = _make_args(["unknown_source"], str(kanon_file), force=True)

        run_remove(args)

        assert kanon_file.read_text() == original

    def test_force_known_and_unknown_removes_known_exits_0(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AC-FUNC-002: remove known unknown --force removes the known block; unknown is skipped; exits 0."""
        content = (
            "GITBASE=https://git.example.com\n"
            "KANON_SOURCE_known_a_URL=https://example.com/known_a.git\n"
            "KANON_SOURCE_known_a_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_known_a_PATH=repo-specs/known_a.xml\n"
            "KANON_SOURCE_known_a_NAME=known_a\n"
            "KANON_SOURCE_known_a_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(content)
        args = _make_args(["known_a", "unknown_source"], str(kanon_file), force=True)

        result = run_remove(args)

        assert result == 0
        after = kanon_file.read_text()
        assert "KANON_SOURCE_known_a_URL" not in after
        assert "KANON_SOURCE_known_a_REF" not in after
        assert "KANON_SOURCE_known_a_PATH" not in after
        assert "KANON_SOURCE_known_a_NAME" not in after
        assert "KANON_SOURCE_known_a_GITBASE" not in after
        assert "GITBASE=https://git.example.com" in after

    def test_no_force_unknown_exits_1(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """AC-FUNC-003: remove unknown (no --force) still exits 1 with the spec-canonical error."""
        kanon_file = tmp_path / ".kanon"
        original = self._KNOWN_CONTENT
        kanon_file.write_text(original)
        args = _make_args(["unknown_source"], str(kanon_file), force=False)

        with pytest.raises(SystemExit) as exc_info:
            run_remove(args)

        assert exc_info.value.code != 0
        stderr = capsys.readouterr().err
        assert "not fully present in .kanon" in stderr
        assert kanon_file.read_text() == original

    def test_force_dry_run_unknown_exits_0_no_diff_output(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AC-FUNC-004: remove unknown --dry-run --force exits 0; no '-' lines printed; file unchanged."""
        kanon_file = tmp_path / ".kanon"
        original = self._KNOWN_CONTENT
        kanon_file.write_text(original)
        args = _make_args(["unknown_source"], str(kanon_file), force=True, dry_run=True)

        result = run_remove(args)

        assert result == 0
        stdout = capsys.readouterr().out
        assert not any(line.startswith("-") for line in stdout.splitlines())
        assert kanon_file.read_text() == original

    def test_force_help_text_updated(self) -> None:
        """AC-FUNC-005: --force help text no longer says 'Reserved for future use'."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        remove_parser = subparsers.choices["remove"]

        force_action = next(
            (a for a in remove_parser._actions if "--force" in (a.option_strings or [])),
            None,
        )
        assert force_action is not None
        assert "Reserved for future use" not in (force_action.help or "")
        assert "skip" in (force_action.help or "").lower()

    def test_force_two_unknown_exits_0_file_unchanged(self, tmp_path: pathlib.Path) -> None:
        """With two unknown sources and --force, both are silently skipped; file is unchanged."""
        kanon_file = tmp_path / ".kanon"
        original = self._KNOWN_CONTENT
        kanon_file.write_text(original)
        args = _make_args(["unknown_a", "unknown_b"], str(kanon_file), force=True)

        result = run_remove(args)

        assert result == 0
        assert kanon_file.read_text() == original

    def test_force_atomicity_known_pair_removed_in_single_write(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-002 atomicity: two known sources + one unknown --force writes all known removals atomically."""
        content = (
            "GITBASE=https://git.example.com\n"
            "KANON_SOURCE_known_a_URL=https://example.com/known_a.git\n"
            "KANON_SOURCE_known_a_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_known_a_PATH=repo-specs/known_a.xml\n"
            "KANON_SOURCE_known_a_NAME=known_a\n"
            "KANON_SOURCE_known_a_GITBASE=https://example.com\n"
            "KANON_SOURCE_known_b_URL=https://example.com/known_b.git\n"
            "KANON_SOURCE_known_b_REF=refs/tags/2.0.0\n"
            "KANON_SOURCE_known_b_PATH=repo-specs/known_b.xml\n"
            "KANON_SOURCE_known_b_NAME=known_b\n"
            "KANON_SOURCE_known_b_GITBASE=https://example.com\n"
        )
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(content)
        args = _make_args(["known_a", "known_b", "unknown_source"], str(kanon_file), force=True)

        result = run_remove(args)

        assert result == 0
        after = kanon_file.read_text()
        assert "KANON_SOURCE_known_a_" not in after
        assert "KANON_SOURCE_known_b_" not in after
        assert "GITBASE=https://git.example.com" in after
