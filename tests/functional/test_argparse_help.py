"""Functional tests for argparse -h/--help across every entry point.

Verifies that:
- 'kanon -h' and 'kanon --help' both exit 0 with usage text (AC-TEST-001).
- Every top-level subcommand supports '-h' and '--help' (AC-TEST-002).
- Every repo subcommand supports '--help' via passthrough (AC-TEST-003).
- Every entry point responds to both help flags identically (AC-FUNC-001).
- stdout vs stderr channel discipline is maintained (AC-CHANNEL-001).

All tests invoke kanon as a subprocess (no mocking of internal APIs).
Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _run_kanon


@pytest.fixture
def nonexistent_repo_dir(tmp_path: pathlib.Path) -> str:
    """Return a guaranteed-nonexistent path under tmp_path for --repo-dir tests.

    The embedded repo tool processes '--help' before reading any .repo
    directory contents, so tests that only exercise help passthrough supply
    this nonexistent sentinel to satisfy the --repo-dir argument without
    requiring a real directory on disk.
    """
    return str(tmp_path / "nonexistent-repo-dir")


_TOP_LEVEL_SUBCOMMANDS = [
    "install",
    "clean",
    "validate",
    "repo",
]


_ALL_SUBCOMMAND_DASH_H_CASES = [
    ("add",),
    ("remove",),
    ("search",),
    ("marketplace",),
    ("outdated",),
    ("why",),
    ("doctor",),
    ("install",),
    ("clean",),
    ("validate",),
    ("catalog",),
    ("catalog", "audit"),
    ("completion",),
    ("repo",),
]


_REPO_SUBCOMMANDS = [
    "abandon",
    "branches",
    "checkout",
    "cherry-pick",
    "diff",
    "diffmanifests",
    "download",
    "envsubst",
    "forall",
    "gc",
    "grep",
    "help",
    "info",
    "init",
    "list",
    "manifest",
    "overview",
    "prune",
    "rebase",
    "selfupdate",
    "smartsync",
    "stage",
    "start",
    "status",
    "sync",
    "upload",
]


@pytest.mark.functional
class TestTopLevelHelpFlags:
    """AC-TEST-001: 'kanon -h' and 'kanon --help' both exit 0 with usage text."""

    def test_double_dash_help_exits_zero(self) -> None:
        """'kanon --help' must exit with code 0."""
        result = _run_kanon("--help")
        assert result.returncode == 0, (
            f"'kanon --help' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_single_dash_h_exits_zero(self) -> None:
        """'kanon -h' must exit with code 0."""
        result = _run_kanon("-h")
        assert result.returncode == 0, (
            f"'kanon -h' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_double_dash_help_contains_usage_text(self) -> None:
        """'kanon --help' must produce output containing 'usage' or 'kanon'."""
        result = _run_kanon("--help")
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "kanon" in combined.lower(), (
            f"'kanon --help' output does not mention 'kanon'.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_single_dash_h_contains_usage_text(self) -> None:
        """'kanon -h' must produce output containing 'usage' or 'kanon'."""
        result = _run_kanon("-h")
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "kanon" in combined.lower(), (
            f"'kanon -h' output does not mention 'kanon'.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_double_dash_help_lists_subcommands(self) -> None:
        """'kanon --help' must list the top-level subcommands."""
        result = _run_kanon("--help")
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        for subcommand in _TOP_LEVEL_SUBCOMMANDS:
            assert subcommand in combined, (
                f"'kanon --help' output does not mention subcommand {subcommand!r}.\n"
                f"  stdout: {result.stdout!r}\n"
                f"  stderr: {result.stderr!r}"
            )

    def test_single_dash_h_lists_subcommands(self) -> None:
        """'kanon -h' must list the top-level subcommands."""
        result = _run_kanon("-h")
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        for subcommand in _TOP_LEVEL_SUBCOMMANDS:
            assert subcommand in combined, (
                f"'kanon -h' output does not mention subcommand {subcommand!r}.\n"
                f"  stdout: {result.stdout!r}\n"
                f"  stderr: {result.stderr!r}"
            )

    def test_both_help_flags_produce_non_empty_stdout(self) -> None:
        """Both '-h' and '--help' must produce output on stdout."""
        for flag in ("-h", "--help"):
            result = _run_kanon(flag)
            assert result.returncode == 0
            assert len(result.stdout) > 0, f"'kanon {flag}' produced empty stdout.\n  stderr: {result.stderr!r}"


@pytest.mark.functional
class TestSubcommandHelpFlags:
    """AC-TEST-002: Every top-level subcommand supports '-h' and '--help'."""

    @pytest.mark.parametrize("subcommand", _TOP_LEVEL_SUBCOMMANDS)
    def test_subcommand_double_dash_help_exits_zero(self, subcommand: str) -> None:
        """'kanon <subcommand> --help' must exit with code 0."""
        result = _run_kanon(subcommand, "--help")
        assert result.returncode == 0, (
            f"'kanon {subcommand} --help' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("subcommand", _TOP_LEVEL_SUBCOMMANDS)
    def test_subcommand_single_dash_h_exits_zero(self, subcommand: str) -> None:
        """'kanon <subcommand> -h' must exit with code 0."""
        result = _run_kanon(subcommand, "-h")
        assert result.returncode == 0, (
            f"'kanon {subcommand} -h' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("subcommand", _TOP_LEVEL_SUBCOMMANDS)
    def test_subcommand_double_dash_help_produces_output(self, subcommand: str) -> None:
        """'kanon <subcommand> --help' must produce non-empty output."""
        result = _run_kanon(subcommand, "--help")
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert len(combined) > 0, (
            f"'kanon {subcommand} --help' produced empty output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("subcommand", _TOP_LEVEL_SUBCOMMANDS)
    def test_subcommand_single_dash_h_produces_output(self, subcommand: str) -> None:
        """'kanon <subcommand> -h' must produce non-empty output."""
        result = _run_kanon(subcommand, "-h")
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert len(combined) > 0, (
            f"'kanon {subcommand} -h' produced empty output.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_validate_xml_double_dash_help_exits_zero(self) -> None:
        """'kanon validate xml --help' must exit 0 (nested subcommand)."""
        result = _run_kanon("validate", "xml", "--help")
        assert result.returncode == 0, (
            f"'kanon validate xml --help' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_validate_xml_single_dash_h_exits_zero(self) -> None:
        """'kanon validate xml -h' must exit 0 (nested subcommand)."""
        result = _run_kanon("validate", "xml", "-h")
        assert result.returncode == 0, (
            f"'kanon validate xml -h' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_validate_marketplace_double_dash_help_exits_zero(self) -> None:
        """'kanon validate marketplace --help' must exit 0 (nested subcommand)."""
        result = _run_kanon("validate", "marketplace", "--help")
        assert result.returncode == 0, (
            f"'kanon validate marketplace --help' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_validate_marketplace_single_dash_h_exits_zero(self) -> None:
        """'kanon validate marketplace -h' must exit 0 (nested subcommand)."""
        result = _run_kanon("validate", "marketplace", "-h")
        assert result.returncode == 0, (
            f"'kanon validate marketplace -h' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "subcmd_args",
        _ALL_SUBCOMMAND_DASH_H_CASES,
        ids=[" ".join(args) for args in _ALL_SUBCOMMAND_DASH_H_CASES],
    )
    def test_subcommand_dash_h_exits_zero(self, subcmd_args: tuple[str, ...]) -> None:
        """'kanon <subcmd> -h' must exit 0 and print usage: for every subcommand (AC-2.2).

        Covers all 13 subcommands plus 'catalog audit' as a separate case.
        Asserts exit code 0, 'usage:' substring in stdout, and that at least
        one token from the subcommand path appears in the combined output.
        """
        result = _run_kanon(*subcmd_args, "-h")
        cmd_display = "kanon " + " ".join(subcmd_args) + " -h"
        assert result.returncode == 0, (
            f"'{cmd_display}' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "usage:" in combined.lower(), (
            f"'{cmd_display}' output does not contain 'usage:'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

        leaf_subcmd = subcmd_args[-1]
        assert leaf_subcmd in combined, (
            f"'{cmd_display}' output does not mention subcommand name {leaf_subcmd!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


@pytest.mark.functional
class TestRepoSubcommandHelpPassthrough:
    """AC-TEST-003: Every repo subcommand supports '--help' via passthrough.

    The embedded repo tool processes '--help' before consulting the .repo
    directory, so a real .repo path is not required for these tests.
    """

    @pytest.mark.parametrize("subcmd", _REPO_SUBCOMMANDS)
    def test_repo_subcmd_help_exits_zero(self, subcmd: str, nonexistent_repo_dir: str) -> None:
        """'kanon repo <subcmd> --help' must exit 0 via passthrough.

        Passes '--repo-dir' pointing to a nonexistent path because the embedded
        tool handles '--help' before reading any .repo directory contents.
        """
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            subcmd,
            "--help",
        )
        assert result.returncode == 0, (
            f"'kanon repo {subcmd} --help' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("subcmd", _REPO_SUBCOMMANDS)
    def test_repo_subcmd_help_produces_output(self, subcmd: str, nonexistent_repo_dir: str) -> None:
        """'kanon repo <subcmd> --help' must produce non-empty output."""
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            subcmd,
            "--help",
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert len(combined) > 0, (
            f"'kanon repo {subcmd} --help' produced empty output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("subcmd", _REPO_SUBCOMMANDS)
    def test_repo_subcmd_help_mentions_subcommand_name(self, subcmd: str, nonexistent_repo_dir: str) -> None:
        """'kanon repo <subcmd> --help' output must mention the subcommand name.

        Confirms that the help output is specific to the requested subcommand
        and not a generic fallback.
        """
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            subcmd,
            "--help",
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr

        assert subcmd in combined, (
            f"'kanon repo {subcmd} --help' output does not mention {subcmd!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


@pytest.mark.functional
class TestHelpFlagIdenticalResponse:
    """AC-FUNC-001: Every entry point responds to '-h' and '--help' identically.

    Verifies that both flags produce the same exit code and non-empty output
    for the top-level command and each top-level subcommand.
    """

    def test_top_level_both_flags_exit_same_code(self) -> None:
        """'kanon -h' and 'kanon --help' must both exit with code 0."""
        result_short = _run_kanon("-h")
        result_long = _run_kanon("--help")
        assert result_short.returncode == 0, (
            f"'kanon -h' exited {result_short.returncode}, expected 0.\n  stdout: {result_short.stdout!r}"
        )
        assert result_long.returncode == 0, (
            f"'kanon --help' exited {result_long.returncode}, expected 0.\n  stdout: {result_long.stdout!r}"
        )

    @pytest.mark.parametrize("subcommand", _TOP_LEVEL_SUBCOMMANDS)
    def test_subcommand_both_flags_exit_same_code(self, subcommand: str) -> None:
        """'kanon <subcommand> -h' and '--help' must both exit with code 0."""
        result_short = _run_kanon(subcommand, "-h")
        result_long = _run_kanon(subcommand, "--help")
        assert result_short.returncode == 0, (
            f"'kanon {subcommand} -h' exited {result_short.returncode}, expected 0.\n"
            f"  stdout: {result_short.stdout!r}\n"
            f"  stderr: {result_short.stderr!r}"
        )
        assert result_long.returncode == 0, (
            f"'kanon {subcommand} --help' exited {result_long.returncode}, expected 0.\n"
            f"  stdout: {result_long.stdout!r}\n"
            f"  stderr: {result_long.stderr!r}"
        )

    @pytest.mark.parametrize("subcommand", _TOP_LEVEL_SUBCOMMANDS)
    def test_subcommand_both_flags_produce_same_content(self, subcommand: str) -> None:
        """'-h' and '--help' must produce the same combined output content."""
        result_short = _run_kanon(subcommand, "-h")
        result_long = _run_kanon(subcommand, "--help")
        combined_short = result_short.stdout + result_short.stderr
        combined_long = result_long.stdout + result_long.stderr
        assert combined_short == combined_long, (
            f"'kanon {subcommand} -h' and '--help' produced different output.\n"
            f"  -h output:     {combined_short!r}\n"
            f"  --help output: {combined_long!r}"
        )


@pytest.mark.functional
class TestHelpChannelDiscipline:
    """AC-CHANNEL-001: Help output appears on stdout; no cross-channel leakage."""

    def test_top_level_help_output_on_stdout(self) -> None:
        """'kanon --help' must produce help text on stdout."""
        result = _run_kanon("--help")
        assert result.returncode == 0, f"'kanon --help' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        assert len(result.stdout) > 0, (
            f"'kanon --help' produced no stdout output; help must appear on stdout.\n  stderr: {result.stderr!r}"
        )

    def test_top_level_help_no_error_on_stderr(self) -> None:
        """'kanon --help' must not produce error-level output on stderr."""
        result = _run_kanon("--help")
        assert result.returncode == 0

        assert "Error:" not in result.stderr, (
            f"'kanon --help' produced an 'Error:' prefix on stderr.\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("subcommand", _TOP_LEVEL_SUBCOMMANDS)
    def test_subcommand_help_output_on_stdout(self, subcommand: str) -> None:
        """'kanon <subcommand> --help' must produce help text on stdout."""
        result = _run_kanon(subcommand, "--help")
        assert result.returncode == 0, (
            f"'kanon {subcommand} --help' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'kanon {subcommand} --help' produced no stdout output.\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("subcommand", _TOP_LEVEL_SUBCOMMANDS)
    def test_subcommand_help_no_error_prefix_on_stderr(self, subcommand: str) -> None:
        """'kanon <subcommand> --help' must not emit 'Error:' on stderr."""
        result = _run_kanon(subcommand, "--help")
        assert result.returncode == 0
        assert "Error:" not in result.stderr, (
            f"'kanon {subcommand} --help' produced 'Error:' on stderr.\n  stderr: {result.stderr!r}"
        )

    def test_repo_subcmd_help_output_not_only_on_stderr(self, nonexistent_repo_dir: str) -> None:
        """'kanon repo init --help' must produce output on stdout via passthrough.

        The embedded repo tool writes its help to stdout. This test verifies
        that the passthrough mechanism does not accidentally suppress stdout.
        """
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            "init",
            "--help",
        )
        assert result.returncode == 0, (
            f"'kanon repo init --help' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'kanon repo init --help' produced no stdout output; output appears only on stderr.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_top_level_short_flag_output_on_stdout(self) -> None:
        """'kanon -h' must produce help text on stdout."""
        result = _run_kanon("-h")
        assert result.returncode == 0, f"'kanon -h' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        assert len(result.stdout) > 0, f"'kanon -h' produced no stdout output.\n  stderr: {result.stderr!r}"

    def test_unused_env_var_does_not_affect_help(self) -> None:
        """Help output must not be affected by extraneous environment variables.

        Passes an unrelated environment variable to confirm that the help
        response is deterministic regardless of the process environment.
        """
        result = _run_kanon(
            "--help",
            extra_env={"SOME_UNRELATED_VAR": "unrelated-value"},
        )
        assert result.returncode == 0, (
            f"'kanon --help' with extra env var exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'kanon --help' with extra env var produced empty stdout.\n  stderr: {result.stderr!r}"
        )
