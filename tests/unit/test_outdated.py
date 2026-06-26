"""Unit tests for the kanon outdated command.

Covers:
- Row construction for all upgrade-type values: none, patch, minor, major, prerelease.
- Missing catalog source error (no flag, no env).
- Missing .kanon file error.
- Zero PEP 440-parseable tags loud error propagation.
- Locked SHA from lockfile path.
- Live-resolve when no lockfile path.

AC-TEST-001
"""

import argparse
import pathlib

import pytest

from kanon_cli.commands.outdated import (
    OutdatedRow,
    _compute_upgrade_type,
    _build_row,
    run,
)


def _make_args(
    catalog_source: str | None = "file:///fake/catalog@HEAD",
    kanon_file: str = "/fake/.kanon",
    lock_file: str | None = None,
    format: str = "table",
    fail_on_upgrade: bool = False,
) -> argparse.Namespace:
    """Build a minimal argparse Namespace matching the outdated subcommand signature."""
    return argparse.Namespace(
        catalog_source=catalog_source,
        kanon_file=kanon_file,
        lock_file=lock_file,
        format=format,
        fail_on_upgrade=fail_on_upgrade,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "current, latest_matching, expected",
    [
        ("1.0.0", "1.0.0", "none"),
        ("1.0.0", "1.0.1", "patch"),
        ("1.0.1", "1.1.0", "minor"),
        ("1.1.0", "2.0.0", "major"),
        ("1.0.0", "1.0.1a1", "prerelease"),
        ("1.0.0rc1", "1.0.0", "patch"),
    ],
)
class TestComputeUpgradeType:
    def test_upgrade_type(self, current: str, latest_matching: str, expected: str) -> None:
        result = _compute_upgrade_type(current, latest_matching)
        assert result == expected, (
            f"_compute_upgrade_type({current!r}, {latest_matching!r}) returned {result!r}, expected {expected!r}"
        )


@pytest.mark.unit
class TestOutdatedRowDataclass:
    def test_outdated_row_fields(self) -> None:
        row = OutdatedRow(
            name="foo",
            current="1.0.0",
            latest_matching_spec="1.0.1",
            latest_available="1.1.0",
            upgrade_type="patch",
        )
        assert row.name == "foo"
        assert row.current == "1.0.0"
        assert row.latest_matching_spec == "1.0.1"
        assert row.latest_available == "1.1.0"
        assert row.upgrade_type == "patch"

    def test_outdated_row_none_upgrade(self) -> None:
        row = OutdatedRow(
            name="bar",
            current="2.0.0",
            latest_matching_spec="2.0.0",
            latest_available="2.0.0",
            upgrade_type="none",
        )
        assert row.upgrade_type == "none"


@pytest.mark.unit
class TestMissingCatalogSource:
    def test_missing_catalog_source_exits_nonzero(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No --catalog-source and no KANON_CATALOG_SOURCE env var must exit non-zero."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_FOO_URL=file:///some/repo\nKANON_SOURCE_FOO_REF=>=1.0.0\nKANON_SOURCE_FOO_PATH=./foo\nKANON_SOURCE_FOO_NAME=FOO\nKANON_SOURCE_FOO_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)
        args = _make_args(catalog_source=None, kanon_file=str(kanon_file))
        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code != 0

    def test_missing_catalog_source_writes_to_stderr(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Error message must be emitted to stderr with the standard ERROR: prefix."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_FOO_URL=file:///some/repo\nKANON_SOURCE_FOO_REF=>=1.0.0\nKANON_SOURCE_FOO_PATH=./foo\nKANON_SOURCE_FOO_NAME=FOO\nKANON_SOURCE_FOO_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)
        args = _make_args(catalog_source=None, kanon_file=str(kanon_file))
        with pytest.raises(SystemExit):
            run(args)
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err
        assert "catalog" in captured.err.lower()


@pytest.mark.unit
class TestMalformedCatalogSourceFormat:
    def test_malformed_catalog_source_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """A catalog source with no '@ref' delimiter must exit non-zero."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_FOO_URL=file:///some/repo\nKANON_SOURCE_FOO_REF=>=1.0.0\nKANON_SOURCE_FOO_PATH=./foo\nKANON_SOURCE_FOO_NAME=FOO\nKANON_SOURCE_FOO_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)

        args = _make_args(catalog_source="no-ref-delimiter-here", kanon_file=str(kanon_file))
        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code != 0

    def test_malformed_catalog_source_writes_error_to_stderr(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Error message for malformed format must go to stderr with ERROR: prefix."""
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_FOO_URL=file:///some/repo\nKANON_SOURCE_FOO_REF=>=1.0.0\nKANON_SOURCE_FOO_PATH=./foo\nKANON_SOURCE_FOO_NAME=FOO\nKANON_SOURCE_FOO_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)
        args = _make_args(catalog_source="no-ref-delimiter-here", kanon_file=str(kanon_file))
        with pytest.raises(SystemExit):
            run(args)
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err


@pytest.mark.unit
class TestMissingKanonFile:
    def test_missing_kanon_file_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """Absent .kanon file at --kanon-file path must exit non-zero."""
        missing_path = str(tmp_path / "does_not_exist" / ".kanon")
        args = _make_args(kanon_file=missing_path)
        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code != 0

    def test_missing_kanon_file_names_path_in_error(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Error message must name the missing path."""
        missing_path = str(tmp_path / "no_such" / ".kanon")
        args = _make_args(kanon_file=missing_path)
        with pytest.raises(SystemExit):
            run(args)
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err
        assert "no_such" in captured.err


@pytest.mark.unit
class TestBuildRowFromLockfile:
    """_build_row returns current from lockfile when lockfile entry is present."""

    def test_current_from_lockfile(self) -> None:
        """When a lock_sha is provided, current column must use it."""
        source = {
            "url": "file:///some/repo",
            "ref": "refs/tags/>=1.0.0,<1.1",
            "path": "./foo",
        }
        available_tags = [
            "refs/tags/1.0.0",
            "refs/tags/1.0.1",
            "refs/tags/1.1.0",
        ]

        row = _build_row(
            name="foo",
            source=source,
            available_tags=available_tags,
            lock_ref="refs/tags/1.0.0",
        )
        assert row.current == "1.0.0"
        assert row.latest_matching_spec == "1.0.1"
        assert row.latest_available == "1.1.0"
        assert row.upgrade_type == "patch"

    def test_current_none_upgrade_from_lockfile(self) -> None:
        """When locked ref equals latest matching spec, upgrade_type is none."""
        source = {
            "url": "file:///some/repo",
            "ref": "refs/tags/>=1.0.0,<1.1",
            "path": "./foo",
        }
        available_tags = [
            "refs/tags/1.0.0",
            "refs/tags/1.0.1",
            "refs/tags/1.1.0",
        ]
        row = _build_row(
            name="foo",
            source=source,
            available_tags=available_tags,
            lock_ref="refs/tags/1.0.1",
        )
        assert row.current == "1.0.1"
        assert row.latest_matching_spec == "1.0.1"
        assert row.upgrade_type == "none"

    def test_minor_upgrade_type(self) -> None:
        """When latest_matching_spec has a higher minor than current, upgrade_type is minor."""
        source = {
            "url": "file:///some/repo",
            "ref": "refs/tags/>=1.0.0",
            "path": "./foo",
        }
        available_tags = [
            "refs/tags/1.0.0",
            "refs/tags/1.1.0",
            "refs/tags/1.2.0",
        ]
        row = _build_row(
            name="foo",
            source=source,
            available_tags=available_tags,
            lock_ref="refs/tags/1.0.0",
        )
        assert row.current == "1.0.0"
        assert row.latest_matching_spec == "1.2.0"
        assert row.upgrade_type == "minor"

    def test_major_upgrade_type(self) -> None:
        """When latest_matching_spec has a higher major than current, upgrade_type is major."""
        source = {
            "url": "file:///some/repo",
            "ref": "refs/tags/>=1.0.0",
            "path": "./foo",
        }
        available_tags = [
            "refs/tags/1.0.0",
            "refs/tags/2.0.0",
            "refs/tags/3.0.0",
        ]
        row = _build_row(
            name="foo",
            source=source,
            available_tags=available_tags,
            lock_ref="refs/tags/1.0.0",
        )
        assert row.current == "1.0.0"
        assert row.latest_matching_spec == "3.0.0"
        assert row.upgrade_type == "major"

    def test_prerelease_upgrade_type(self) -> None:
        """When latest_matching_spec is a prerelease, upgrade_type is prerelease."""
        source = {
            "url": "file:///some/repo",
            "ref": "refs/tags/>=1.0.0",
            "path": "./foo",
        }
        available_tags = [
            "refs/tags/1.0.0",
            "refs/tags/1.0.1a1",
        ]
        row = _build_row(
            name="foo",
            source=source,
            available_tags=available_tags,
            lock_ref="refs/tags/1.0.0",
        )
        assert row.current == "1.0.0"
        assert row.latest_matching_spec == "1.0.1a1"
        assert row.upgrade_type == "prerelease"


@pytest.mark.unit
class TestBuildRowLiveResolve:
    """When lock_ref is None, current is resolved live against the constraint."""

    def test_live_resolve_uses_constraint(self) -> None:
        """Without a lockfile, current is resolved from the constraint + available tags."""
        source = {
            "url": "file:///some/repo",
            "ref": "refs/tags/>=1.0.0,<1.1",
            "path": "./foo",
        }
        available_tags = [
            "refs/tags/1.0.0",
            "refs/tags/1.0.1",
            "refs/tags/1.1.0",
        ]
        row = _build_row(
            name="foo",
            source=source,
            available_tags=available_tags,
            lock_ref=None,
        )

        assert row.current == "1.0.1"

        assert row.latest_matching_spec == "1.0.1"
        assert row.latest_available == "1.1.0"
        assert row.upgrade_type == "none"


@pytest.mark.unit
class TestZeroPep440TagsError:
    def test_zero_pep440_tags_raises_value_error_with_loud_message(self) -> None:
        """_build_row must propagate the loud error from _resolve_constraint_from_tags."""
        source = {
            "url": "file:///some/repo",
            "ref": "refs/tags/>=1.0.0",
            "path": "./foo",
        }

        non_pep440_tags = [
            "refs/tags/release-1.0.0",
            "refs/tags/hotfix-abc",
        ]
        with pytest.raises(ValueError, match="No PEP 440-parseable version tags found"):
            _build_row(
                name="foo",
                source=source,
                available_tags=non_pep440_tags,
                lock_ref=None,
            )

    def test_zero_pep440_tags_error_includes_remediation(self) -> None:
        """The loud error message must include the catalog audit remediation pointer."""
        source = {
            "url": "file:///some/repo",
            "ref": "refs/tags/>=1.0.0",
            "path": "./foo",
        }
        non_pep440_tags = ["refs/tags/release-1.0.0"]
        try:
            _build_row(
                name="foo",
                source=source,
                available_tags=non_pep440_tags,
                lock_ref=None,
            )
            pytest.fail("Expected ValueError to be raised")
        except ValueError as exc:
            assert "kanon catalog audit" in str(exc)


@pytest.mark.unit
class TestFormatTable:
    """Tests for the _format_table helper."""

    def test_format_table_single_row(self) -> None:
        """_format_table emits a header, separator, and one data row."""
        from kanon_cli.commands.outdated import _format_table

        rows = [
            OutdatedRow(
                name="foo",
                current="1.0.0",
                latest_matching_spec="1.0.1",
                latest_available="1.1.0",
                upgrade_type="patch",
            )
        ]
        output = _format_table(rows)
        assert "name" in output
        assert "current" in output
        assert "latest-matching-spec" in output
        assert "latest-available" in output
        assert "upgrade-type" in output
        assert "foo" in output
        assert "1.0.0" in output
        assert "1.0.1" in output
        assert "1.1.0" in output
        assert "patch" in output
        assert output.endswith("\n")

    def test_format_table_header_separator_structure(self) -> None:
        """_format_table output has header line, separator, then data lines."""
        from kanon_cli.commands.outdated import _format_table

        rows = [
            OutdatedRow(
                name="bar",
                current="2.0.0",
                latest_matching_spec="2.0.0",
                latest_available="2.0.0",
                upgrade_type="none",
            )
        ]
        output = _format_table(rows)
        lines = output.rstrip("\n").split("\n")

        assert len(lines) >= 3

        assert "-" in lines[1]


@pytest.mark.unit
class TestResolveLockRef:
    """Tests for _resolve_lock_ref helper."""

    def test_returns_none_when_path_is_none(self) -> None:
        """_resolve_lock_ref returns None when lock_file_path is None."""
        from kanon_cli.commands.outdated import _resolve_lock_ref

        result = _resolve_lock_ref("foo", None)
        assert result is None

    def test_returns_none_when_file_does_not_exist(self, tmp_path: pathlib.Path) -> None:
        """_resolve_lock_ref returns None when lockfile does not exist."""
        from kanon_cli.commands.outdated import _resolve_lock_ref

        missing = tmp_path / "nonexistent.lock"
        result = _resolve_lock_ref("foo", missing)
        assert result is None

    def test_returns_none_when_source_not_in_lockfile(self, tmp_path: pathlib.Path) -> None:
        """_resolve_lock_ref returns None when lockfile exists but source name is absent."""
        from kanon_cli.commands.outdated import _resolve_lock_ref

        sha = "a" * 40
        lock_file = tmp_path / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 5\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "BAR"\n'
            'name = "BAR"\n'
            'url = "file:///some/repo"\n'
            'ref_spec = ">=1.0.0"\n'
            'resolved_ref = "refs/tags/1.0.0"\n'
            f'resolved_sha = "{sha}"\n'
            'path = "./bar"\n'
        )

        result = _resolve_lock_ref("FOO", lock_file)
        assert result is None


@pytest.mark.unit
class TestRegister:
    """Tests for the register() function in outdated.py."""

    def test_register_adds_outdated_subparser(self) -> None:
        """register() adds the 'outdated' subparser to the provided subparsers action."""
        import argparse

        from kanon_cli.commands.outdated import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        assert "outdated" in subparsers.choices

    def test_register_sets_func_to_run(self) -> None:
        """register() sets defaults func to run()."""
        import argparse

        from kanon_cli.commands.outdated import register, run

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        args = root_parser.parse_args(["outdated", "--catalog-source", "file:///x@HEAD"])
        assert args.func is run

    def test_register_outdated_accepts_format_flag(self) -> None:
        """'outdated' subparser accepts --format table."""
        import argparse

        from kanon_cli.commands.outdated import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        args = root_parser.parse_args(["outdated", "--catalog-source", "file:///x@HEAD", "--format", "table"])
        assert args.format == "table"

    def test_outdated_short_dash_h_exits_0(self) -> None:
        """kanon outdated -h exits 0 (add_help=True on the outdated subparser)."""
        import argparse

        from kanon_cli.commands.outdated import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        with pytest.raises(SystemExit) as exc_info:
            root_parser.parse_args(["outdated", "-h"])
        assert exc_info.value.code == 0

    def test_outdated_subparser_has_add_help_true(self) -> None:
        """The 'outdated' subparser has add_help=True set explicitly."""
        import argparse

        from kanon_cli.commands.outdated import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        outdated_parser = subparsers.choices["outdated"]
        assert outdated_parser.add_help is True, "outdated subparser must have add_help=True so '-h' is accepted"


@pytest.mark.unit
class TestRunHappyPath:
    """Test run() with patched network calls to achieve coverage on the main dispatch path."""

    def test_run_outputs_table_with_patched_tags(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """run() emits a table row for each source when _list_tags is patched."""
        from unittest.mock import patch

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=file:///unused\n"
            "CLAUDE_MARKETPLACES_DIR=/tmp/.claude\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_FOO_URL=file:///some/repo\n"
            "KANON_SOURCE_FOO_REF=>=1.0.0,<1.1\n"
            "KANON_SOURCE_FOO_PATH=./foo\n"
            "KANON_SOURCE_FOO_NAME=FOO\n"
            "KANON_SOURCE_FOO_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)

        fake_tags = ["refs/tags/1.0.0", "refs/tags/1.0.1", "refs/tags/1.1.0"]

        args = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
            lock_file=None,
        )

        with patch("kanon_cli.commands.outdated._list_tags", return_value=fake_tags):
            result = run(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "FOO" in captured.out
        assert "1.0.1" in captured.out
        assert "1.1.0" in captured.out
        assert "none" in captured.out

    def test_run_uses_lockfile_when_explicit_path_given(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """run() reads current from lockfile when --lock-file is given and file exists."""
        from unittest.mock import patch

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=file:///unused\n"
            "CLAUDE_MARKETPLACES_DIR=/tmp/.claude\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_FOO_URL=file:///some/repo\n"
            "KANON_SOURCE_FOO_REF=>=1.0.0,<1.1\n"
            "KANON_SOURCE_FOO_PATH=./foo\n"
            "KANON_SOURCE_FOO_NAME=FOO\n"
            "KANON_SOURCE_FOO_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)

        lock_file = tmp_path / ".kanon.lock"
        sha = "a" * 40
        lock_file.write_text(
            "schema_version = 5\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "FOO"\n'
            'name = "FOO"\n'
            'url = "file:///some/repo"\n'
            'ref_spec = ">=1.0.0,<1.1"\n'
            'resolved_ref = "refs/tags/1.0.0"\n'
            f'resolved_sha = "{sha}"\n'
            'path = "./foo"\n'
        )

        fake_tags = ["refs/tags/1.0.0", "refs/tags/1.0.1", "refs/tags/1.1.0"]

        args = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
        )

        with patch("kanon_cli.commands.outdated._list_tags", return_value=fake_tags):
            result = run(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "1.0.0" in captured.out
        assert "1.0.1" in captured.out
        assert "patch" in captured.out

    def test_run_propagates_zero_pep440_tags_error(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """run() exits non-zero and writes ERROR to stderr on zero-PEP440-tags condition."""
        from unittest.mock import patch

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=file:///unused\n"
            "CLAUDE_MARKETPLACES_DIR=/tmp/.claude\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_FOO_URL=file:///some/repo\n"
            "KANON_SOURCE_FOO_REF=>=1.0.0\n"
            "KANON_SOURCE_FOO_PATH=./foo\n"
            "KANON_SOURCE_FOO_NAME=FOO\n"
            "KANON_SOURCE_FOO_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)

        non_pep440_tags = ["refs/tags/release-1.0.0"]

        args = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
        )

        with pytest.raises(SystemExit) as exc_info:
            with patch("kanon_cli.commands.outdated._list_tags", return_value=non_pep440_tags):
                run(args)

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err
