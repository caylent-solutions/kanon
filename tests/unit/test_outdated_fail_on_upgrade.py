"""Unit tests for 'kanon outdated --fail-on-upgrade' flag.

Covers AC-TEST-001:
- all-none-flag-set (exit 0)
- one-patch-flag-set (exit 1)
- one-drift-flag-set (exit 1)
- any-upgrade-flag-unset (exit 0)
- zero-sources-flag-set (exit 0)

AC-FUNC-001: --fail-on-upgrade is a boolean argparse flag (default False).
AC-FUNC-002: With flag, exit 1 when any row has upgrade-type != "none".
AC-FUNC-003: With flag, exit 0 when all rows have upgrade-type == "none".
AC-FUNC-004: Without flag, exit 0 regardless of upgrade availability.
AC-FUNC-005: Row content unchanged regardless of flag.
AC-FUNC-006: With flag and zero sources, exit 0.
"""

import argparse
import pathlib

import pytest

from kanon_cli.commands.outdated import run


def _make_args(
    catalog_source: str | None = "file:///fake/catalog@HEAD",
    kanon_file: str = "/fake/.kanon",
    lock_file: str | None = None,
    format: str = "table",
    fail_on_upgrade: bool = False,
) -> argparse.Namespace:
    """Build a minimal argparse Namespace matching the outdated subcommand."""
    return argparse.Namespace(
        catalog_source=catalog_source,
        kanon_file=kanon_file,
        lock_file=lock_file,
        format=format,
        fail_on_upgrade=fail_on_upgrade,
    )


def _write_kanon_file(path: pathlib.Path, sources: list[dict[str, str]]) -> None:
    """Write a .kanon file with the given sources.

    Each source dict must have keys: name (uppercase), url, ref, path.
    """
    lines = [
        "GITBASE=file:///unused",
        "CLAUDE_MARKETPLACES_DIR=/tmp/.claude",
        "KANON_MARKETPLACE_INSTALL=false",
    ]
    for source in sources:
        name = source["name"]
        lines.append(f"KANON_SOURCE_{name}_URL={source['url']}")
        lines.append(f"KANON_SOURCE_{name}_REF={source['ref']}")
        lines.append(f"KANON_SOURCE_{name}_PATH={source['path']}")
        lines.append(f"KANON_SOURCE_{name}_NAME={name}")
        lines.append(f"KANON_SOURCE_{name}_GITBASE=https://example.com")
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o644)


@pytest.mark.unit
class TestFailOnUpgradeFlagRegistration:
    """AC-FUNC-001: --fail-on-upgrade is a boolean store-true flag, default False."""

    def test_flag_registered_on_outdated_subparser(self) -> None:
        """register() adds --fail-on-upgrade to the outdated subparser."""
        from kanon_cli.commands.outdated import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)

        args = root_parser.parse_args(["outdated", "--catalog-source", "file:///x@HEAD"])
        assert args.fail_on_upgrade is False

    def test_flag_sets_true_when_supplied(self) -> None:
        """--fail-on-upgrade sets fail_on_upgrade=True when passed on the CLI."""
        from kanon_cli.commands.outdated import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)

        args = root_parser.parse_args(["outdated", "--catalog-source", "file:///x@HEAD", "--fail-on-upgrade"])
        assert args.fail_on_upgrade is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "upgrade_type,fail_on_upgrade,expected_exit_code",
    [
        ("none", True, 0),
        ("patch", True, 1),
        ("minor", True, 1),
        ("major", True, 1),
        ("prerelease", True, 1),
        ("patch", False, 0),
        ("major", False, 0),
        ("none", False, 0),
    ],
)
class TestRunExitCodeWithUpgradeTypes:
    """Parametrized: exit code depends on upgrade-type and --fail-on-upgrade flag."""

    def test_exit_code(
        self,
        upgrade_type: str,
        fail_on_upgrade: bool,
        expected_exit_code: int,
        tmp_path: pathlib.Path,
    ) -> None:
        """run() returns the correct exit code for the given upgrade_type and flag."""
        from unittest.mock import patch

        kanon_file = tmp_path / ".kanon"

        if upgrade_type == "none":
            revision = ">=1.0.0,<1.1"
            available_tags = ["refs/tags/1.0.0", "refs/tags/1.0.1"]
            lock_ref = "refs/tags/1.0.1"
        elif upgrade_type == "patch":
            revision = ">=1.0.0,<1.1"
            available_tags = ["refs/tags/1.0.0", "refs/tags/1.0.1"]
            lock_ref = "refs/tags/1.0.0"
        elif upgrade_type == "minor":
            revision = ">=1.0.0"
            available_tags = ["refs/tags/1.0.0", "refs/tags/1.1.0"]
            lock_ref = "refs/tags/1.0.0"
        elif upgrade_type == "major":
            revision = ">=1.0.0"
            available_tags = ["refs/tags/1.0.0", "refs/tags/2.0.0"]
            lock_ref = "refs/tags/1.0.0"
        else:
            revision = ">=1.0.0"
            available_tags = ["refs/tags/1.0.0", "refs/tags/1.0.1a1"]
            lock_ref = "refs/tags/1.0.0"

        _write_kanon_file(
            kanon_file,
            [{"name": "FOO", "url": "file:///some/repo", "ref": revision, "path": "./foo"}],
        )

        sha = "a" * 40
        lock_file = tmp_path / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 4\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "FOO"\n'
            'name = "FOO"\n'
            'url = "file:///some/repo"\n'
            f'ref_spec = "{revision}"\n'
            f'resolved_ref = "{lock_ref}"\n'
            f'resolved_sha = "{sha}"\n'
            'path = "./foo"\n'
        )

        args = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            fail_on_upgrade=fail_on_upgrade,
        )

        with patch("kanon_cli.commands.outdated._list_tags", return_value=available_tags):
            result = run(args)

        assert result == expected_exit_code, (
            f"upgrade_type={upgrade_type!r}, fail_on_upgrade={fail_on_upgrade}: "
            f"expected exit {expected_exit_code}, got {result}"
        )


@pytest.mark.unit
class TestDriftUpgradeTypeWithFlag:
    """AC-FUNC-002: drift (branch-pinned) counts as available upgrade."""

    def test_drift_with_flag_exits_one(self, tmp_path: pathlib.Path) -> None:
        """When upgrade-type would be 'drift' and flag is set, exit code is 1."""
        from unittest.mock import patch

        kanon_file = tmp_path / ".kanon"
        old_sha = "a" * 40
        new_sha = "b" * 40

        _write_kanon_file(
            kanon_file,
            [{"name": "DRIFT", "url": "file:///some/repo", "ref": "main", "path": "./drift"}],
        )

        lock_file = tmp_path / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 4\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "DRIFT"\n'
            'name = "DRIFT"\n'
            'url = "file:///some/repo"\n'
            'ref_spec = "main"\n'
            'resolved_ref = "main"\n'
            f'resolved_sha = "{old_sha}"\n'
            'path = "./drift"\n'
        )

        args = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            fail_on_upgrade=True,
        )

        with patch("kanon_cli.commands.outdated._list_branch_head", return_value=new_sha):
            result = run(args)

        assert result == 1, f"Expected exit 1 for drift + flag, got {result}"

    def test_drift_without_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-004: drift without --fail-on-upgrade exits 0."""
        from unittest.mock import patch

        kanon_file = tmp_path / ".kanon"
        old_sha = "a" * 40
        new_sha = "b" * 40

        _write_kanon_file(
            kanon_file,
            [{"name": "DRIFT", "url": "file:///some/repo", "ref": "main", "path": "./drift"}],
        )

        lock_file = tmp_path / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 4\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "DRIFT"\n'
            'name = "DRIFT"\n'
            'url = "file:///some/repo"\n'
            'ref_spec = "main"\n'
            'resolved_ref = "main"\n'
            f'resolved_sha = "{old_sha}"\n'
            'path = "./drift"\n'
        )

        args = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            fail_on_upgrade=False,
        )

        with patch("kanon_cli.commands.outdated._list_branch_head", return_value=new_sha):
            result = run(args)

        assert result == 0, f"Expected exit 0 for drift without flag, got {result}"


@pytest.mark.unit
class TestRowContentUnchangedByFlag:
    """AC-FUNC-005: row columns are identical with and without --fail-on-upgrade."""

    def test_row_content_same_with_and_without_flag(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """The table output is identical whether --fail-on-upgrade is set or not."""
        from unittest.mock import patch

        kanon_file = tmp_path / ".kanon"
        _write_kanon_file(
            kanon_file,
            [{"name": "FOO", "url": "file:///some/repo", "ref": ">=1.0.0,<1.1", "path": "./foo"}],
        )

        sha = "a" * 40
        lock_file = tmp_path / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 4\n"
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

        available_tags = ["refs/tags/1.0.0", "refs/tags/1.0.1"]

        args_without_flag = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            fail_on_upgrade=False,
        )
        args_with_flag = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
            lock_file=str(lock_file),
            fail_on_upgrade=True,
        )

        with patch("kanon_cli.commands.outdated._list_tags", return_value=available_tags):
            run(args_without_flag)
            captured_without = capsys.readouterr()

        with patch("kanon_cli.commands.outdated._list_tags", return_value=available_tags):
            run(args_with_flag)
            captured_with = capsys.readouterr()

        assert captured_without.out == captured_with.out, (
            "Table output must be identical with and without --fail-on-upgrade.\n"
            f"Without flag:\n{captured_without.out}\n"
            f"With flag:\n{captured_with.out}"
        )


@pytest.mark.unit
class TestZeroSourcesWithFlag:
    """AC-FUNC-006: zero rows iterated with --fail-on-upgrade -> exit 0.

    parse_kanonenv raises ValueError when no KANON_SOURCE_* blocks are present,
    so this test patches parse_kanonenv to return an empty sources dict and
    KANON_SOURCES list, simulating the zero-sources scenario at the run() level.
    This verifies the exit-code logic handles an empty rows list correctly.
    """

    def test_zero_sources_flag_set_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """With zero sources in the iteration and --fail-on-upgrade, exit 0."""
        from unittest.mock import patch

        kanon_file = tmp_path / ".kanon"

        kanon_file.write_text(
            "GITBASE=file:///unused\n"
            "CLAUDE_MARKETPLACES_DIR=/tmp/.claude\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_PLACEHOLDER_URL=file:///x\n"
            "KANON_SOURCE_PLACEHOLDER_REF=>=1.0.0\n"
            "KANON_SOURCE_PLACEHOLDER_PATH=./x\n"
            "KANON_SOURCE_PLACEHOLDER_NAME=PLACEHOLDER\n"
            "KANON_SOURCE_PLACEHOLDER_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)

        empty_kanonenv: dict = {"KANON_SOURCES": [], "sources": {}}

        args = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
            lock_file=None,
            fail_on_upgrade=True,
        )

        with patch("kanon_cli.commands.outdated.parse_kanonenv", return_value=empty_kanonenv):
            result = run(args)

        assert result == 0, f"Expected exit 0 for zero iterated sources with --fail-on-upgrade, got {result}"
