"""End-to-end CLI invocation tests via subprocess."""

import pytest

from kanon_cli import __version__
from tests.functional.conftest import _run_kanon


@pytest.mark.functional
class TestKanonHelp:
    def test_top_level_help(self) -> None:
        result = _run_kanon("--help")
        assert result.returncode == 0
        assert "install" in result.stdout
        assert "clean" in result.stdout
        assert "validate" in result.stdout

    def test_install_help(self) -> None:
        result = _run_kanon("install", "--help")
        assert result.returncode == 0
        assert "kanonenv_path" in result.stdout

    def test_clean_help(self) -> None:
        result = _run_kanon("clean", "--help")
        assert result.returncode == 0
        assert "kanonenv_path" in result.stdout

    def test_validate_help(self) -> None:
        result = _run_kanon("validate", "--help")
        assert result.returncode == 0
        assert "xml" in result.stdout
        assert "marketplace" in result.stdout

    def test_validate_xml_help(self) -> None:
        result = _run_kanon("validate", "xml", "--help")
        assert result.returncode == 0
        assert "--repo-root" in result.stdout

    def test_validate_marketplace_help(self) -> None:
        result = _run_kanon("validate", "marketplace", "--help")
        assert result.returncode == 0
        assert "--repo-root" in result.stdout


@pytest.mark.functional
class TestKanonVersion:
    def test_version_flag(self) -> None:
        result = _run_kanon("--version")
        assert result.returncode == 0
        assert __version__ in result.stdout


@pytest.mark.functional
class TestKanonBootstrapList:
    def test_bootstrap_list_exits_3(self) -> None:
        # 'kanon bootstrap' was removed in a major release. Every invocation,
        # including 'kanon bootstrap list', exits 3 (EXIT_CODE_DEPRECATED) with
        # the deprecation message; it does not delegate to 'kanon list'.
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3, (
            f"'kanon bootstrap list' expected exit 3 (EXIT_CODE_DEPRECATED), "
            f"got {result.returncode}.\n  stderr: {result.stderr!r}"
        )

    def test_bootstrap_list_deprecation_on_stderr(self) -> None:
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        assert "DEPRECATED" in result.stderr
        assert "docs/migration-bootstrap-to-add.md" in result.stderr
        # The list-arm closest-replacement line points at 'kanon list'.
        assert "kanon list --catalog-source <git-url>@<ref>" in result.stderr, (
            f"'kanon bootstrap list' stderr did not contain the list-arm replacement.\n  stderr: {result.stderr!r}"
        )


@pytest.mark.functional
class TestKanonBootstrapKanon:
    def test_bootstrap_kanon_exits_3(self, tmp_path) -> None:
        # The shim exits 3 and performs no filesystem work; the unknown
        # '--output-dir' flag is ignored (intercept runs before argparse).
        output_dir = tmp_path / "test-project"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert result.returncode == 3, (
            f"'kanon bootstrap kanon --output-dir ...' expected exit 3 (EXIT_CODE_DEPRECATED), "
            f"got {result.returncode}.\n  stderr: {result.stderr!r}"
        )

    def test_bootstrap_kanon_deprecation_on_stderr(self, tmp_path) -> None:
        output_dir = tmp_path / "test-project"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert result.returncode == 3
        assert "DEPRECATED" in result.stderr
        # The add-arm closest-replacement line names the entry.
        assert "kanon add kanon --catalog-source <git-url>@<ref>" in result.stderr, (
            f"'kanon bootstrap kanon' stderr did not contain the add-arm replacement.\n  stderr: {result.stderr!r}"
        )

    def test_bootstrap_kanon_creates_no_files(self, tmp_path) -> None:
        # The shim performs NO work. The (ignored) --output-dir must not be
        # created and no files must appear in tmp_path after exit 3.
        output_dir = tmp_path / "test-project"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert result.returncode == 3
        assert not output_dir.exists(), (
            f"'kanon bootstrap kanon' must not create the output directory.\n"
            f"  output_dir: {output_dir}\n  stderr: {result.stderr!r}"
        )

    def test_bootstrap_kanon_with_existing_kanonenv_exits_3(self, tmp_path) -> None:
        # Even when a .kanon file already exists, the shim exits 3 immediately
        # -- it does not inspect the filesystem.
        (tmp_path / ".kanon").write_text("existing")
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(tmp_path))
        assert result.returncode == 3, (
            f"'kanon bootstrap kanon' with existing .kanon expected exit 3, "
            f"got {result.returncode}.\n  stderr: {result.stderr!r}"
        )

    def test_bootstrap_kanon_with_existing_kanonenv_deprecation_on_stderr(self, tmp_path) -> None:
        # The DEPRECATED message must appear on stderr regardless of whether a
        # .kanon file is already present.
        (tmp_path / ".kanon").write_text("existing")
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(tmp_path))
        assert result.returncode == 3
        assert "DEPRECATED" in result.stderr
        assert "docs/migration-bootstrap-to-add.md" in result.stderr


@pytest.mark.functional
class TestKanonBadSubcommand:
    def test_no_subcommand_exits_2(self) -> None:
        result = _run_kanon()
        assert result.returncode == 2

    def test_invalid_subcommand_exits_2(self) -> None:
        result = _run_kanon("nonexistent")
        assert result.returncode == 2

    def test_install_no_arg_no_kanonenv_exits_1(self) -> None:
        result = _run_kanon("install")
        assert result.returncode == 1
        assert ".kanon" in result.stderr

    def test_clean_no_arg_no_kanonenv_exits_1(self) -> None:
        result = _run_kanon("clean")
        assert result.returncode == 1
        assert ".kanon" in result.stderr

    def test_validate_no_target_exits_2(self) -> None:
        result = _run_kanon("validate")
        assert result.returncode == 2


@pytest.mark.functional
class TestKanonRepo:
    def test_repo_is_registered_as_subcommand(self) -> None:
        """'kanon repo' must be a registered subcommand accessible from the CLI."""
        result = _run_kanon("repo", "--help")
        assert result.returncode == 0
        assert "repo" in result.stdout.lower()

    def test_repo_help_output_not_empty(self) -> None:
        """'kanon repo --help' must produce non-empty help text."""
        result = _run_kanon("repo", "--help")
        assert result.returncode == 0
        assert len(result.stdout) > 0
