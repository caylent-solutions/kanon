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
        # Category (a): bootstrap-specific behavior. 'kanon bootstrap list'
        # is a deprecated invocation. The shim exits 3 (EXIT_CODE_DEPRECATED)
        # per spec Section 4.9 and does not delegate to 'kanon list'.
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3, (
            f"'kanon bootstrap list' expected exit 3 (EXIT_CODE_DEPRECATED), "
            f"got {result.returncode}.\n  stderr: {result.stderr!r}"
        )

    def test_bootstrap_list_deprecated_warn_on_stderr(self) -> None:
        # Category (a): The shim MUST emit the spec R355/R357 WARN substring
        # on stderr for any non-help invocation.
        # The DEPRECATED notice is emitted as a WARN line: spec Section 4.9.
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        assert "WARN: 'kanon bootstrap list' is deprecated. Run instead:" in result.stderr, (
            f"'kanon bootstrap list' stderr did not contain the required deprecation WARN.\n  stderr: {result.stderr!r}"
        )


@pytest.mark.functional
class TestKanonBootstrapKanon:
    def test_bootstrap_kanon_exits_3(self, tmp_path) -> None:
        # Category (a): bootstrap-specific behavior. 'kanon bootstrap kanon'
        # is a deprecated invocation. The shim exits 3 (EXIT_CODE_DEPRECATED)
        # and performs no filesystem work per spec Section 4.9.
        output_dir = tmp_path / "test-project"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert result.returncode == 3, (
            f"'kanon bootstrap kanon --output-dir ...' expected exit 3 (EXIT_CODE_DEPRECATED), "
            f"got {result.returncode}.\n  stderr: {result.stderr!r}"
        )

    def test_bootstrap_kanon_deprecated_warn_on_stderr(self, tmp_path) -> None:
        # Category (a): The shim MUST emit the spec R355/R357 WARN substring
        # on stderr. No filesystem mutation occurs.
        # The DEPRECATED notice is emitted as a WARN line: spec Section 4.9.
        output_dir = tmp_path / "test-project"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert result.returncode == 3
        assert "WARN: 'kanon bootstrap kanon' is deprecated. Run instead:" in result.stderr, (
            f"'kanon bootstrap kanon' stderr did not contain the required deprecation WARN.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bootstrap_kanon_creates_no_files(self, tmp_path) -> None:
        # Category (a): The shim performs NO work. The output directory must
        # not be created and no files must appear in tmp_path after exit 3.
        output_dir = tmp_path / "test-project"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert result.returncode == 3
        assert not output_dir.exists(), (
            f"'kanon bootstrap kanon' must not create the output directory.\n"
            f"  output_dir: {output_dir}\n  stderr: {result.stderr!r}"
        )

    def test_bootstrap_kanon_with_existing_kanonenv_exits_3(self, tmp_path) -> None:
        # Category (a): Even when a .kanon file already exists, the shim
        # exits 3 immediately -- it does not inspect the filesystem.
        (tmp_path / ".kanon").write_text("existing")
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(tmp_path))
        assert result.returncode == 3, (
            f"'kanon bootstrap kanon' with existing .kanon expected exit 3, "
            f"got {result.returncode}.\n  stderr: {result.stderr!r}"
        )

    def test_bootstrap_kanon_with_existing_kanonenv_deprecated_warn_on_stderr(self, tmp_path) -> None:
        # Category (a): DEPRECATED substring must appear on stderr regardless
        # of whether a .kanon file is already present.
        # The DEPRECATED notice is emitted as a WARN line: spec Section 4.9.
        (tmp_path / ".kanon").write_text("existing")
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(tmp_path))
        assert result.returncode == 3
        assert "WARN: 'kanon bootstrap kanon' is deprecated. Run instead:" in result.stderr, (
            f"'kanon bootstrap kanon' with existing .kanon stderr did not contain "
            f"the required deprecation WARN.\n  stderr: {result.stderr!r}"
        )


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
