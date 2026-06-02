"""Integration tests for the uniform `kanon bootstrap` deprecation shim.

`kanon bootstrap` was removed in a major release (a breaking change). EVERY
invocation -- any args, any flags, including `--help`, unknown flags such as
`--marketplace-install`, `kanon bootstrap list`, and bare `kanon bootstrap` --
prints ONE comprehensive deprecation message to stderr and exits non-zero
(`EXIT_CODE_DEPRECATED` == 3). No work is performed and no filesystem access
is made.

These tests invoke `python -m kanon_cli bootstrap ...` via subprocess (the real
running CLI) and assert:
- exit code 3,
- stderr carries the message's key substrings (asserted by substring, never
  byte-for-byte),
- the correct "closest replacement" arm line for the invocation,
- stdout is empty,
- no filesystem mutation occurs.
"""

import pathlib
import subprocess
import sys

import pytest

from kanon_cli.constants import EXIT_CODE_DEPRECATED

# Key substrings every deprecation message must carry, regardless of invocation.
_CORE_SUBSTRINGS = (
    "DEPRECATED",
    "major release",
    "breaking change",
    "kanon list",
    "kanon add",
    "kanon install",
    ".kanon",
    "repo-specs",
    "<catalog-metadata>",
    "docs/migration-bootstrap-to-add.md",
)


def _run_bootstrap(*args: str, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    """Invoke `python -m kanon_cli bootstrap <args>` as a subprocess.

    Args:
        *args: Additional arguments to pass after `bootstrap`.
        cwd: Working directory for the subprocess. Defaults to None (inherit).

    Returns:
        CompletedProcess with returncode, stdout, and stderr as strings.
    """
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", "bootstrap", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def _assert_core_message(stderr: str) -> None:
    """Assert the deprecation message's invocation-independent substrings.

    Args:
        stderr: The captured stderr of a bootstrap subprocess invocation.
    """
    for needle in _CORE_SUBSTRINGS:
        assert needle in stderr, f"Expected {needle!r} in deprecation stderr, got: {stderr!r}"


@pytest.mark.integration
class TestBootstrapShimUniformContract:
    """Every bootstrap invocation exits 3 with the deprecation message on stderr."""

    @pytest.mark.parametrize(
        "args",
        [
            [],
            ["list"],
            ["kanon"],
            ["history"],
            ["--help"],
            ["-h"],
            ["--marketplace-install"],
            ["history", "--marketplace-install"],
            ["list", "--catalog-source", "https://example.com/x.git@main"],
            ["kanon", "--output-dir", "/tmp/should-not-be-created"],
        ],
        ids=[
            "bare",
            "list",
            "entry-kanon",
            "entry-history",
            "long-help",
            "short-help",
            "unknown-flag",
            "entry+unknown-flag",
            "list+catalog-source",
            "entry+output-dir",
        ],
    )
    def test_exit_3_and_core_message(self, args: list[str], tmp_path: pathlib.Path) -> None:
        result = _run_bootstrap(*args, cwd=tmp_path)
        assert result.returncode == EXIT_CODE_DEPRECATED, (
            f"Expected exit {EXIT_CODE_DEPRECATED}, got {result.returncode}.\nstderr: {result.stderr!r}"
        )
        _assert_core_message(result.stderr)

    @pytest.mark.parametrize(
        "args",
        [[], ["list"], ["history"], ["--help"], ["--marketplace-install"]],
        ids=["bare", "list", "entry", "long-help", "unknown-flag"],
    )
    def test_stdout_is_empty(self, args: list[str], tmp_path: pathlib.Path) -> None:
        result = _run_bootstrap(*args, cwd=tmp_path)
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"


@pytest.mark.integration
class TestBootstrapShimHelpIsDeprecated:
    """`kanon bootstrap --help` is NO LONGER help output: it exits 3 with the message."""

    def test_long_help_exits_3_not_zero(self) -> None:
        result = _run_bootstrap("--help")
        assert result.returncode == EXIT_CODE_DEPRECATED, (
            f"Expected exit {EXIT_CODE_DEPRECATED} for `bootstrap --help`, got {result.returncode}.\n"
            f"stderr: {result.stderr!r}"
        )

    def test_long_help_emits_message_on_stderr_not_stdout(self) -> None:
        result = _run_bootstrap("--help")
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"
        _assert_core_message(result.stderr)

    def test_short_help_exits_3(self) -> None:
        result = _run_bootstrap("-h")
        assert result.returncode == EXIT_CODE_DEPRECATED
        _assert_core_message(result.stderr)


@pytest.mark.integration
class TestBootstrapShimUnknownFlagPreviouslyBroke:
    """The previously-broken argparse-error case now emits the deprecation message.

    Before the major release, `kanon bootstrap history --marketplace-install`
    raised an argparse 'unrecognized arguments' error (exit 2). It must now exit
    3 with the deprecation message.
    """

    def test_history_marketplace_install_exits_3(self) -> None:
        result = _run_bootstrap("history", "--marketplace-install")
        assert result.returncode == EXIT_CODE_DEPRECATED, (
            f"Expected exit {EXIT_CODE_DEPRECATED}, got {result.returncode}.\nstderr: {result.stderr!r}"
        )
        _assert_core_message(result.stderr)
        # No argparse usage/unrecognized-arguments error is emitted.
        assert "unrecognized arguments" not in result.stderr, (
            f"argparse error must not appear; the intercept runs before argparse: {result.stderr!r}"
        )

    def test_history_marketplace_install_uses_add_arm(self) -> None:
        result = _run_bootstrap("history", "--marketplace-install")
        # First positional is the entry `history`, so the closest-replacement
        # arm is `kanon add history ...`.
        assert "kanon add history --catalog-source <git-url>@<ref>" in result.stderr, (
            f"Expected the add-arm replacement for entry 'history', got: {result.stderr!r}"
        )


@pytest.mark.integration
class TestBootstrapShimClosestReplacementArm:
    """The 'closest replacement' line reflects the first positional of the tail."""

    def test_list_arm_uses_kanon_list(self) -> None:
        result = _run_bootstrap("list")
        assert "kanon list --catalog-source <git-url>@<ref>" in result.stderr, (
            f"Expected the list-arm replacement, got: {result.stderr!r}"
        )

    def test_entry_arm_uses_kanon_add_with_entry(self) -> None:
        result = _run_bootstrap("acme-tools")
        assert "kanon add acme-tools --catalog-source <git-url>@<ref>" in result.stderr, (
            f"Expected the add-arm replacement for entry 'acme-tools', got: {result.stderr!r}"
        )

    def test_flags_only_tail_uses_generic_entry_arm(self) -> None:
        result = _run_bootstrap("--marketplace-install")
        assert "kanon add <entry> --catalog-source <git-url>@<ref>" in result.stderr, (
            f"Expected the generic add-arm replacement, got: {result.stderr!r}"
        )


@pytest.mark.integration
class TestBootstrapShimNoFilesystemMutation:
    """The shim never performs work: it must not create or touch any path."""

    def test_output_dir_not_created(self, tmp_path: pathlib.Path) -> None:
        scratch = tmp_path / "scratch"
        _run_bootstrap("kanon", "--output-dir", str(scratch), cwd=tmp_path)
        assert not scratch.exists(), (
            f"Expected --output-dir '{scratch}' to NOT be created (shim performs no work), but it exists."
        )

    def test_tmp_path_remains_empty(self, tmp_path: pathlib.Path) -> None:
        scratch = tmp_path / "scratch"
        _run_bootstrap("kanon", "--output-dir", str(scratch), cwd=tmp_path)
        assert list(tmp_path.iterdir()) == [], (
            f"Expected tmp_path to be empty after shim run, but found: {list(tmp_path.iterdir())}"
        )

    def test_sentinel_catalog_source_not_cloned(self, tmp_path: pathlib.Path) -> None:
        """A sentinel --catalog-source must never trigger a clone (no work performed)."""
        result = _run_bootstrap(
            "list",
            "--catalog-source",
            "https://example.com/x.git@main",
            cwd=tmp_path,
        )
        assert result.returncode == EXIT_CODE_DEPRECATED
        assert "Cloning" not in result.stderr, f"Unexpected clone attempt in stderr: {result.stderr!r}"
        assert "fatal:" not in result.stderr, f"Unexpected git fatal in stderr: {result.stderr!r}"
