"""Functional tests for help-text contract: flags in help output match implementation.

Verifies that:
- Every top-level subcommand --help output contains the documented flags
  and positional arguments registered in the parser (AC-TEST-001).
- Every repo subcommand --help output contains documented flags specific to
  that subcommand (AC-TEST-002).
- argparse error messages name the correct argument when a bad value or
  unknown flag is supplied (AC-TEST-003).

Help-text contract definition: the help output must mention the flag names,
positional argument names, and key option strings that appear in the
subcommand's argparse parser registration so that documentation and
implementation stay in sync.

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
    this nonexistent sentinel to satisfy the --repo-dir argument.
    """
    return str(tmp_path / "nonexistent-help-contract-repo-dir")


_SUBCOMMAND_DOCUMENTED_FLAGS: list[tuple[tuple[str, ...], list[str]]] = [
    (
        ("install",),
        ["kanonenv_path"],
    ),
    (
        ("clean",),
        ["kanonenv_path"],
    ),
    (
        ("validate",),
        ["xml", "marketplace"],
    ),
    (
        ("validate", "xml"),
        ["--repo-root"],
    ),
    (
        ("validate", "marketplace"),
        ["--repo-root"],
    ),
    (
        ("repo",),
        ["--repo-dir", "repo_args"],
    ),
]


_REPO_SUBCOMMAND_DOCUMENTED_FLAGS: list[tuple[str, list[str]]] = [
    ("init", ["-u", "--manifest-url", "-b", "--manifest-branch", "-m", "--manifest-name"]),
    ("sync", ["-j", "--jobs"]),
    ("status", ["-v", "--verbose", "-q", "--quiet"]),
    ("abandon", ["-h", "--help"]),
    ("branches", ["-h", "--help"]),
    ("checkout", ["-h", "--help"]),
    ("diff", ["-h", "--help"]),
    ("forall", ["-c", "-v", "--verbose"]),
    ("grep", ["-h", "--help"]),
    ("info", ["-h", "--help"]),
    ("list", ["-h", "--help"]),
    ("manifest", ["-h", "--help"]),
    ("overview", ["-h", "--help"]),
    ("prune", ["-h", "--help"]),
    ("rebase", ["-h", "--help"]),
    ("start", ["-h", "--help"]),
    ("upload", ["-h", "--help"]),
    ("smartsync", ["-j", "--jobs"]),
    ("download", ["-h", "--help"]),
    ("envsubst", ["-h", "--help"]),
    ("gc", ["-h", "--help"]),
    ("selfupdate", ["-h", "--help"]),
    ("stage", ["-h", "--help"]),
    ("cherry-pick", ["-h", "--help"]),
    ("diffmanifests", ["-h", "--help"]),
    ("help", ["-h", "--help"]),
]


_ARGUMENT_ERROR_CASES: list[tuple[tuple[str, ...], str, str]] = [
    (("--not-a-valid-kanon-flag",), "--not-a-valid-kanon-flag", "unknown top-level flag"),
    (("nosuchsubcommand",), "nosuchsubcommand", "unknown subcommand"),
    (("install", "--no-such-install-option"), "--no-such-install-option", "unknown install flag"),
    (("clean", "--no-such-clean-option"), "--no-such-clean-option", "unknown clean flag"),
    (("validate", "--no-such-validate-option"), "--no-such-validate-option", "unknown validate flag"),
    (("validate", "xml", "--no-such-xml-option"), "--no-such-xml-option", "unknown validate xml flag"),
]


@pytest.mark.functional
class TestTopLevelSubcommandHelpContract:
    """AC-TEST-001: every top-level subcommand --help mentions documented flags.

    For each registered subcommand, the --help output must contain the flag
    names and positional argument names declared in the argparse registration
    so that the help text stays in sync with the implementation.
    """

    @pytest.mark.parametrize(
        "subcommand_argv,expected_strings",
        [pytest.param(argv, strings, id=" ".join(argv)) for argv, strings in _SUBCOMMAND_DOCUMENTED_FLAGS],
    )
    def test_help_mentions_documented_flags(
        self,
        subcommand_argv: tuple[str, ...],
        expected_strings: list[str],
    ) -> None:
        """'kanon <subcommand> --help' must mention every documented flag/arg.

        Verifies that every flag name and positional argument name registered
        in the subcommand's argparse parser appears in the --help output so
        that the help text contract and the implementation are in sync.
        """
        result = _run_kanon(*subcommand_argv, "--help")
        assert result.returncode == 0, (
            f"'kanon {' '.join(subcommand_argv)} --help' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        for expected in expected_strings:
            assert expected in combined, (
                f"'kanon {' '.join(subcommand_argv)} --help' output does not mention {expected!r}.\n"
                f"  stdout: {result.stdout!r}\n"
                f"  stderr: {result.stderr!r}"
            )

    @pytest.mark.parametrize(
        "subcommand_argv,expected_strings",
        [pytest.param(argv, strings, id=" ".join(argv)) for argv, strings in _SUBCOMMAND_DOCUMENTED_FLAGS],
    )
    def test_help_exits_zero(
        self,
        subcommand_argv: tuple[str, ...],
        expected_strings: list[str],
    ) -> None:
        """'kanon <subcommand> --help' must exit with code 0.

        Verifies that every top-level subcommand accepts --help without error
        regardless of whether other required arguments are omitted.
        """
        result = _run_kanon(*subcommand_argv, "--help")
        assert result.returncode == 0, (
            f"'kanon {' '.join(subcommand_argv)} --help' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "subcommand_argv,expected_strings",
        [pytest.param(argv, strings, id=" ".join(argv)) for argv, strings in _SUBCOMMAND_DOCUMENTED_FLAGS],
    )
    def test_help_produces_output_on_stdout(
        self,
        subcommand_argv: tuple[str, ...],
        expected_strings: list[str],
    ) -> None:
        """'kanon <subcommand> --help' must produce non-empty output on stdout.

        argparse writes help text to stdout by default. Verifies that the
        help contract output reaches stdout so users see it without redirecting
        stderr.
        """
        result = _run_kanon(*subcommand_argv, "--help")
        assert result.returncode == 0
        assert len(result.stdout) > 0, (
            f"'kanon {' '.join(subcommand_argv)} --help' produced no stdout output.\n  stderr: {result.stderr!r}"
        )

    def test_top_level_help_lists_all_subcommands(self) -> None:
        """'kanon --help' must list the registered top-level subcommands.

        The top-level help text is the entry point for discovering available
        commands. All registered subcommands must be visible there.
        """
        result = _run_kanon("--help")
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        for subcmd in ("install", "clean", "validate", "repo"):
            assert subcmd in combined, (
                f"'kanon --help' does not mention top-level subcommand {subcmd!r}.\n"
                f"  stdout: {result.stdout!r}\n"
                f"  stderr: {result.stderr!r}"
            )

    def test_top_level_help_mentions_version_flag(self) -> None:
        """'kanon --help' must mention the --version flag."""
        result = _run_kanon("--help")
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "--version" in combined, (
            f"'kanon --help' does not mention '--version'.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


@pytest.mark.functional
class TestRepoSubcommandHelpContract:
    """AC-TEST-002: every repo subcommand --help mentions documented flags.

    For each repo subcommand, the --help passthrough output must contain the
    flag names documented for that subcommand by the embedded repo tool so
    that the passthrough mechanism does not suppress or alter the help output.
    """

    @pytest.mark.parametrize(
        "subcmd,expected_strings",
        [pytest.param(subcmd, strings, id=subcmd) for subcmd, strings in _REPO_SUBCOMMAND_DOCUMENTED_FLAGS],
    )
    def test_repo_subcmd_help_mentions_documented_flags(
        self,
        subcmd: str,
        expected_strings: list[str],
        nonexistent_repo_dir: str,
    ) -> None:
        """'kanon repo <subcmd> --help' output must contain documented flags.

        The embedded repo tool processes '--help' before reading any .repo
        directory. A nonexistent --repo-dir is therefore sufficient.
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
        combined = result.stdout + result.stderr
        for expected in expected_strings:
            assert expected in combined, (
                f"'kanon repo {subcmd} --help' output does not mention {expected!r}.\n"
                f"  stdout: {result.stdout!r}\n"
                f"  stderr: {result.stderr!r}"
            )

    @pytest.mark.parametrize(
        "subcmd,expected_strings",
        [pytest.param(subcmd, strings, id=subcmd) for subcmd, strings in _REPO_SUBCOMMAND_DOCUMENTED_FLAGS],
    )
    def test_repo_subcmd_help_exits_zero(
        self,
        subcmd: str,
        expected_strings: list[str],
        nonexistent_repo_dir: str,
    ) -> None:
        """'kanon repo <subcmd> --help' must exit with code 0."""
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

    @pytest.mark.parametrize(
        "subcmd,expected_strings",
        [pytest.param(subcmd, strings, id=subcmd) for subcmd, strings in _REPO_SUBCOMMAND_DOCUMENTED_FLAGS],
    )
    def test_repo_subcmd_help_mentions_subcommand_name(
        self,
        subcmd: str,
        expected_strings: list[str],
        nonexistent_repo_dir: str,
    ) -> None:
        """'kanon repo <subcmd> --help' output must mention the subcommand name.

        Verifies that the passthrough does not return generic help that omits
        the specific subcommand context requested by the user.
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
            f"'kanon repo {subcmd} --help' output does not mention the subcommand name {subcmd!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_kanon_repo_help_mentions_repo_dir_flag(self) -> None:
        """'kanon repo --help' must document --repo-dir in the kanon layer.

        The --repo-dir flag is registered in the kanon layer's repo subparser.
        It must appear in 'kanon repo --help' output to keep the contract
        between the kanon layer and its help text in sync.
        """
        result = _run_kanon("repo", "--help")
        assert result.returncode == 0, (
            f"'kanon repo --help' exited {result.returncode}, expected 0.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "--repo-dir" in combined, (
            f"'kanon repo --help' output does not mention '--repo-dir'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


@pytest.mark.functional
class TestArgparseErrorArgumentName:
    """AC-TEST-003: argparse error messages point to the correct argument name.

    When an unknown flag or invalid value is supplied, the error message must
    name the specific argument that caused the error so users can identify
    which flag or positional is wrong and correct it.
    """

    @pytest.mark.parametrize(
        "argv,expected_fragment,description",
        [
            pytest.param(argv, fragment, description, id=description)
            for argv, fragment, description in _ARGUMENT_ERROR_CASES
        ],
    )
    def test_error_message_names_the_argument(
        self,
        argv: tuple[str, ...],
        expected_fragment: str,
        description: str,
    ) -> None:
        """argparse error output must contain the specific argument name.

        Verifies that when kanon is invoked with an unrecognised flag the
        error message includes the flag name so users have an actionable
        diagnostic pointing to the problem argument.
        """
        result = _run_kanon(*argv)
        assert result.returncode != 0, (
            f"'{' '.join(('kanon',) + argv)}' exited 0 but a non-zero exit was expected for error case {description!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert expected_fragment in combined, (
            f"argparse error for {description!r} does not name {expected_fragment!r}.\n  combined output: {combined!r}"
        )

    @pytest.mark.parametrize(
        "argv,expected_fragment,description",
        [
            pytest.param(argv, fragment, description, id=description)
            for argv, fragment, description in _ARGUMENT_ERROR_CASES
        ],
    )
    def test_error_message_on_stderr(
        self,
        argv: tuple[str, ...],
        expected_fragment: str,
        description: str,
    ) -> None:
        """argparse error output must appear on stderr, not stdout.

        Verifies the channel discipline for error messages: error text goes
        to stderr so that tooling that parses stdout does not receive error
        diagnostic text mixed with normal output.
        """
        result = _run_kanon(*argv)
        assert result.returncode != 0
        assert len(result.stderr) > 0, (
            f"argparse error for {description!r} produced empty stderr.\n  stdout: {result.stdout!r}"
        )

    def test_error_exit_code_for_unknown_flag_is_two(self) -> None:
        """An unknown top-level flag must produce exit code 2 (argparse error).

        argparse uses exit code 2 for argument parsing errors. This verifies
        that the kanon layer does not suppress or transform that exit code.
        """
        result = _run_kanon("--not-a-valid-kanon-flag-for-exit-code-test")
        assert result.returncode == 2, (
            f"Unknown flag should produce exit code 2, got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_error_exit_code_for_unknown_subcommand_is_two(self) -> None:
        """An unknown subcommand must produce exit code 2 (argparse error).

        argparse uses exit code 2 for unrecognised argument errors. This
        verifies consistent exit code behaviour across error classes.
        """
        result = _run_kanon("nosuchsubcommand-for-exit-code-test")
        assert result.returncode == 2, (
            f"Unknown subcommand should produce exit code 2, got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_validate_no_subcommand_names_required_choice(self) -> None:
        """'kanon validate' without xml or marketplace must produce a clear error.

        Verifies that missing the required validate sub-subcommand produces an
        error message that helps users understand what to provide.
        """
        result = _run_kanon("validate")
        assert result.returncode != 0, (
            f"'kanon validate' with no sub-subcommand should exit non-zero, "
            f"got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr

        assert any(term in combined for term in ("xml", "marketplace", "validate")), (
            f"'kanon validate' error does not mention any of 'xml', 'marketplace', 'validate'.\n"
            f"  combined: {combined!r}"
        )


@pytest.mark.functional
class TestHelpContractChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr discipline for help-text contract tests.

    Verifies that help text appears on stdout and error messages appear on
    stderr so that tool pipelines can process each stream independently.
    """

    def test_install_help_on_stdout(self) -> None:
        """'kanon install --help' must write help text to stdout."""
        result = _run_kanon("install", "--help")
        assert result.returncode == 0
        assert len(result.stdout) > 0, f"'kanon install --help' produced no stdout output.\n  stderr: {result.stderr!r}"

    def test_validate_xml_help_on_stdout(self) -> None:
        """'kanon validate xml --help' must write help text to stdout."""
        result = _run_kanon("validate", "xml", "--help")
        assert result.returncode == 0
        assert len(result.stdout) > 0, (
            f"'kanon validate xml --help' produced no stdout output.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_not_on_stdout(self) -> None:
        """An unknown top-level flag error must not appear on stdout."""
        result = _run_kanon("--unknown-flag-channel-test")
        assert result.returncode != 0
        assert len(result.stdout) == 0, (
            f"'kanon --unknown-flag-channel-test' produced unexpected stdout.\n  stdout: {result.stdout!r}"
        )

    def test_repo_dir_help_on_stdout(self, nonexistent_repo_dir: str) -> None:
        """'kanon repo init --help' must write help text to stdout via passthrough."""
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
            f"'kanon repo init --help' produced no stdout; help must appear on stdout.\n  stderr: {result.stderr!r}"
        )
