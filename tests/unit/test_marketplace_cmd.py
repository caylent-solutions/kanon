"""Unit tests for the kanon marketplace command module (commands/marketplace.py).

Covers the per-dependency marketplace management command (spec Section 4.4 /
FR-18):

- ``enable <alias>`` writes ``KANON_SOURCE_<alias>_MARKETPLACE=true``.
- ``disable <alias>`` removes the line (absence is the canonical false).
- ``status`` renders an explicit ``=false`` and an absent line identically.
- Unknown alias -> clear error (non-zero exit).
- ``enable`` on a non-marketplace type -> pretty error (non-zero exit).
- ``status`` with no deps -> exit 0 with an empty table.
- The handlers edit only ``.kanon`` and never write ``.kanon.lock``.

The core/marketplace.py shared module is covered by tests/unit/test_marketplace.py
and is intentionally not exercised here.
"""

import argparse
import pathlib

import pytest

from kanon_cli.commands.marketplace import (
    _format_status_table,
    register,
    run_disable,
    run_enable,
    run_status,
)
from kanon_cli.constants import CATALOG_TYPE_CLAUDE_MARKETPLACE

# A complete alias-keyed source block carries the five required suffixes. The
# tests assemble .kanon content from these so no on-disk schema literal is
# duplicated across cases (DRY).
_BLOCK_SUFFIXES = ("_URL", "_REF", "_PATH", "_NAME", "_GITBASE")

# Sentinel values used to populate the required block fields. Their exact content
# is irrelevant to the marketplace command (it never resolves them); they exist
# only so the alias is discoverable via its _URL line.
_FIELD_VALUES = {
    "_URL": "https://example.com/org/repo.git",
    "_REF": "1.0.0",
    "_PATH": "repo-specs/entry-marketplace.xml",
    "_NAME": "entry",
    "_GITBASE": "https://example.com/org",
}

_MARKETPLACE_LINE = "KANON_SOURCE_{alias}_MARKETPLACE={value}"


def _source_block(alias: str, *, marketplace: str | None = None) -> list[str]:
    """Build the .kanon lines for one alias block.

    Args:
        alias: The canonical source alias.
        marketplace: When ``None`` no ``_MARKETPLACE`` line is written; otherwise
            the literal value to write (``"true"`` or ``"false"``).

    Returns:
        The block lines (no trailing newlines).
    """
    lines = [f"KANON_SOURCE_{alias}{suffix}={_FIELD_VALUES[suffix]}" for suffix in _BLOCK_SUFFIXES]
    if marketplace is not None:
        lines.append(_MARKETPLACE_LINE.format(alias=alias, value=marketplace))
    return lines


def _write_kanon(tmp_path: pathlib.Path, *blocks: list[str]) -> pathlib.Path:
    """Write a .kanon file assembled from the given alias blocks and return it.

    Args:
        tmp_path: The pytest temporary directory.
        *blocks: One or more block line lists (e.g. from :func:`_source_block`).

    Returns:
        The path to the written ``.kanon`` file.
    """
    kanon_file = tmp_path / ".kanon"
    body: list[str] = []
    for block in blocks:
        body.extend(block)
        body.append("")  # blank separator between blocks
    kanon_file.write_text("\n".join(body) + "\n", encoding="utf-8")
    return kanon_file


def _namespace(alias: str | None, kanon_file: pathlib.Path, *, show_all: bool = False) -> argparse.Namespace:
    """Build an argparse namespace for the marketplace handlers.

    Args:
        alias: The alias argument (``None`` for ``status``).
        kanon_file: The ``.kanon`` path.
        show_all: The ``--all`` flag value (only used by ``status``).

    Returns:
        A namespace with the attributes the handlers read.
    """
    ns = argparse.Namespace(kanon_file=str(kanon_file), show_all=show_all)
    if alias is not None:
        ns.alias = alias
    return ns


@pytest.mark.unit
class TestRegister:
    """Verify the marketplace subcommand registers enable/disable/status."""

    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="kanon")
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        return parser

    def test_enable_subcommand_parses(self) -> None:
        parser = self._build_parser()
        args = parser.parse_args(["marketplace", "enable", "foo"])
        assert args.command == "marketplace"
        assert args.marketplace_command == "enable"
        assert args.alias == "foo"
        assert args.func is run_enable

    def test_disable_subcommand_parses(self) -> None:
        parser = self._build_parser()
        args = parser.parse_args(["marketplace", "disable", "foo"])
        assert args.marketplace_command == "disable"
        assert args.func is run_disable

    def test_status_subcommand_parses(self) -> None:
        parser = self._build_parser()
        args = parser.parse_args(["marketplace", "status"])
        assert args.marketplace_command == "status"
        assert args.func is run_status
        assert args.show_all is False

    def test_status_all_flag_parses(self) -> None:
        parser = self._build_parser()
        args = parser.parse_args(["marketplace", "status", "--all"])
        assert args.show_all is True


@pytest.mark.unit
class TestEnable:
    """Verify ``marketplace enable`` semantics."""

    def test_enable_marketplace_false_becomes_true(self, tmp_path: pathlib.Path) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("foo", marketplace="false"))
        rc = run_enable(_namespace("foo", kanon_file))
        assert rc == 0
        assert "KANON_SOURCE_foo_MARKETPLACE=true" in kanon_file.read_text(encoding="utf-8")
        assert "KANON_SOURCE_foo_MARKETPLACE=false" not in kanon_file.read_text(encoding="utf-8")

    def test_enable_is_idempotent_when_already_true(self, tmp_path: pathlib.Path) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("foo", marketplace="true"))
        rc = run_enable(_namespace("foo", kanon_file))
        assert rc == 0
        text = kanon_file.read_text(encoding="utf-8")
        assert text.count("KANON_SOURCE_foo_MARKETPLACE=true") == 1

    def test_enable_accepts_original_entry_name(self, tmp_path: pathlib.Path) -> None:
        # Foo-Bar normalises to foo_bar via derive_source_name.
        kanon_file = _write_kanon(tmp_path, _source_block("foo_bar", marketplace="false"))
        rc = run_enable(_namespace("Foo-Bar", kanon_file))
        assert rc == 0
        assert "KANON_SOURCE_foo_bar_MARKETPLACE=true" in kanon_file.read_text(encoding="utf-8")

    def test_enable_unknown_alias_errors(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("foo", marketplace="true"))
        with pytest.raises(SystemExit) as exc_info:
            run_enable(_namespace("nope", kanon_file))
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "unknown source alias" in err
        assert "nope" in err
        # The unrelated alias's flag must be untouched.
        assert "KANON_SOURCE_foo_MARKETPLACE=true" in kanon_file.read_text(encoding="utf-8")

    def test_enable_non_marketplace_type_errors(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        # A dependency without any _MARKETPLACE line is not a marketplace type.
        kanon_file = _write_kanon(tmp_path, _source_block("plain", marketplace=None))
        with pytest.raises(SystemExit) as exc_info:
            run_enable(_namespace("plain", kanon_file))
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "not a" in err
        assert CATALOG_TYPE_CLAUDE_MARKETPLACE in err
        # No _MARKETPLACE line was created.
        assert "KANON_SOURCE_plain_MARKETPLACE" not in kanon_file.read_text(encoding="utf-8")

    def test_enable_missing_kanon_file_errors(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        kanon_file = tmp_path / ".kanon"
        with pytest.raises(SystemExit) as exc_info:
            run_enable(_namespace("foo", kanon_file))
        assert exc_info.value.code == 1
        assert "no .kanon file" in capsys.readouterr().err


@pytest.mark.unit
class TestDisable:
    """Verify ``marketplace disable`` semantics."""

    def test_disable_removes_the_line(self, tmp_path: pathlib.Path) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("foo", marketplace="true"))
        rc = run_disable(_namespace("foo", kanon_file))
        assert rc == 0
        text = kanon_file.read_text(encoding="utf-8")
        assert "KANON_SOURCE_foo_MARKETPLACE" not in text
        # The rest of the block survives.
        assert "KANON_SOURCE_foo_URL=" in text

    def test_disable_never_writes_false(self, tmp_path: pathlib.Path) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("foo", marketplace="true"))
        run_disable(_namespace("foo", kanon_file))
        assert "=false" not in kanon_file.read_text(encoding="utf-8")

    def test_disable_already_disabled_is_noop(self, tmp_path: pathlib.Path) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("foo", marketplace=None))
        before = kanon_file.read_text(encoding="utf-8")
        rc = run_disable(_namespace("foo", kanon_file))
        assert rc == 0
        assert kanon_file.read_text(encoding="utf-8") == before

    def test_disable_unknown_alias_errors(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("foo", marketplace="true"))
        with pytest.raises(SystemExit) as exc_info:
            run_disable(_namespace("nope", kanon_file))
        assert exc_info.value.code == 1
        assert "unknown source alias" in capsys.readouterr().err

    def test_disable_explicit_false_line_removed(self, tmp_path: pathlib.Path) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("foo", marketplace="false"))
        rc = run_disable(_namespace("foo", kanon_file))
        assert rc == 0
        assert "KANON_SOURCE_foo_MARKETPLACE" not in kanon_file.read_text(encoding="utf-8")


@pytest.mark.unit
class TestStatus:
    """Verify ``marketplace status`` rendering."""

    def test_status_renders_false_and_absent_identically(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        kanon_file = _write_kanon(
            tmp_path,
            _source_block("explicit_false", marketplace="false"),
            _source_block("absent", marketplace=None),
        )
        rc = run_status(_namespace(None, kanon_file, show_all=True))
        assert rc == 0
        out = capsys.readouterr().out
        explicit_line = next(line for line in out.splitlines() if line.startswith("explicit_false"))
        absent_line = next(line for line in out.splitlines() if line.startswith("absent"))
        # Both render the disabled setting token.
        assert explicit_line.split()[-1] == "disabled"
        assert absent_line.split()[-1] == "disabled"

    def test_status_renders_enabled(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("aws_control_tower", marketplace="true"))
        rc = run_status(_namespace(None, kanon_file, show_all=True))
        assert rc == 0
        out = capsys.readouterr().out
        row = next(line for line in out.splitlines() if line.startswith("aws_control_tower"))
        assert CATALOG_TYPE_CLAUDE_MARKETPLACE in row
        assert row.split()[-1] == "enabled"

    def test_status_without_all_hides_non_marketplace(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        kanon_file = _write_kanon(
            tmp_path,
            _source_block("market", marketplace="true"),
            _source_block("plain", marketplace=None),
        )
        rc = run_status(_namespace(None, kanon_file, show_all=False))
        assert rc == 0
        out = capsys.readouterr().out
        assert any(line.startswith("market") for line in out.splitlines())
        assert not any(line.startswith("plain") for line in out.splitlines())

    def test_status_all_shows_non_marketplace(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        kanon_file = _write_kanon(
            tmp_path,
            _source_block("market", marketplace="true"),
            _source_block("plain", marketplace=None),
        )
        rc = run_status(_namespace(None, kanon_file, show_all=True))
        assert rc == 0
        out = capsys.readouterr().out
        plain_row = next(line for line in out.splitlines() if line.startswith("plain"))
        # The non-marketplace dep renders the unknown-type placeholder and disabled.
        assert "--" in plain_row
        assert plain_row.split()[-1] == "disabled"

    def test_status_no_deps_exits_zero_empty_table(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("# no sources here\n", encoding="utf-8")
        rc = run_status(_namespace(None, kanon_file, show_all=True))
        assert rc == 0
        out_lines = capsys.readouterr().out.splitlines()
        # Only the header line is printed -- no data rows.
        assert len(out_lines) == 1
        assert out_lines[0].startswith("ALIAS")

    def test_format_status_table_header_only_when_empty(self) -> None:
        rendered = _format_status_table([])
        assert len(rendered) == 1
        assert rendered[0].startswith("ALIAS")


@pytest.mark.unit
class TestLockUntouched:
    """Verify the handlers never write a .kanon.lock entry (spec Section 4.4)."""

    def test_enable_does_not_create_lock(self, tmp_path: pathlib.Path) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("foo", marketplace="false"))
        run_enable(_namespace("foo", kanon_file))
        assert not (tmp_path / ".kanon.lock").exists()

    def test_disable_does_not_create_lock(self, tmp_path: pathlib.Path) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("foo", marketplace="true"))
        run_disable(_namespace("foo", kanon_file))
        assert not (tmp_path / ".kanon.lock").exists()

    def test_enable_leaves_existing_lock_untouched(self, tmp_path: pathlib.Path) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("foo", marketplace="false"))
        lock_file = tmp_path / ".kanon.lock"
        sentinel = "SENTINEL-LOCK-CONTENT\n"
        lock_file.write_text(sentinel, encoding="utf-8")
        run_enable(_namespace("foo", kanon_file))
        assert lock_file.read_text(encoding="utf-8") == sentinel

    def test_disable_leaves_existing_lock_untouched(self, tmp_path: pathlib.Path) -> None:
        kanon_file = _write_kanon(tmp_path, _source_block("foo", marketplace="true"))
        lock_file = tmp_path / ".kanon.lock"
        sentinel = "SENTINEL-LOCK-CONTENT\n"
        lock_file.write_text(sentinel, encoding="utf-8")
        run_disable(_namespace("foo", kanon_file))
        assert lock_file.read_text(encoding="utf-8") == sentinel
