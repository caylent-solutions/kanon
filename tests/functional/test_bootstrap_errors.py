"""Functional tests for `kanon bootstrap` invocations that previously errored.

`kanon bootstrap` was removed in a major release (a breaking change). The
invocation is intercepted before argparse, so cases that previously produced an
argparse usage error (exit 2) -- bare `kanon bootstrap` with no positional, an
unknown flag such as `--marketplace-install` -- now uniformly print the
deprecation message to stderr and exit 3. No work is performed and no Python
traceback is emitted.

These tests invoke the running CLI (`python -m kanon_cli`) and assert by key
substrings (never byte-for-byte).
"""

import pytest

from tests.functional.conftest import _run_kanon


@pytest.mark.functional
class TestBareBootstrapIsDeprecatedNotArgparseError:
    """Bare `kanon bootstrap` (no positional) exits 3, NOT an argparse exit-2 error.

    Before the major release, omitting the positional raised an argparse
    "required" error (exit 2). The intercept now runs before argparse, so bare
    `kanon bootstrap` exits 3 with the deprecation message instead.
    """

    def test_bare_bootstrap_exits_3(self) -> None:
        result = _run_kanon("bootstrap")
        assert result.returncode == 3, (
            f"Bare 'kanon bootstrap' should exit 3 (deprecated), got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_bare_bootstrap_message_on_stderr(self) -> None:
        result = _run_kanon("bootstrap")
        assert result.returncode == 3
        assert "DEPRECATED" in result.stderr
        assert "docs/migration-bootstrap-to-add.md" in result.stderr

    def test_bare_bootstrap_no_argparse_required_error(self) -> None:
        result = _run_kanon("bootstrap")
        assert result.returncode == 3
        # The old argparse "the following arguments are required" / "unrecognized
        # arguments" diagnostics must not appear.
        assert "the following arguments are required" not in result.stderr
        assert "unrecognized arguments" not in result.stderr

    def test_bare_bootstrap_uses_generic_add_arm(self) -> None:
        result = _run_kanon("bootstrap")
        assert result.returncode == 3
        # No positional -> the generic add-arm closest-replacement line.
        assert "kanon add <entry> --catalog-source <git-url>@<ref>" in result.stderr, (
            f"Expected the generic add-arm replacement, got: {result.stderr!r}"
        )

    def test_bare_bootstrap_nothing_on_stdout(self) -> None:
        result = _run_kanon("bootstrap")
        assert result.returncode == 3
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"


@pytest.mark.functional
class TestBootstrapUnknownFlagIsDeprecated:
    """Unknown flags such as `--marketplace-install` exit 3, NOT an argparse error.

    Before the major release, `kanon bootstrap history --marketplace-install`
    raised an argparse "unrecognized arguments" error (exit 2). It now exits 3
    with the deprecation message.
    """

    def test_unknown_flag_exits_3(self) -> None:
        result = _run_kanon("bootstrap", "history", "--marketplace-install")
        assert result.returncode == 3, (
            f"Expected exit 3 for unknown bootstrap flag, got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_unknown_flag_no_argparse_error(self) -> None:
        result = _run_kanon("bootstrap", "history", "--marketplace-install")
        assert result.returncode == 3
        assert "unrecognized arguments" not in result.stderr, (
            f"argparse error must not appear; the intercept runs before argparse: {result.stderr!r}"
        )

    def test_unknown_flag_uses_entry_add_arm(self) -> None:
        result = _run_kanon("bootstrap", "history", "--marketplace-install")
        assert result.returncode == 3
        # First positional `history` -> add-arm replacement naming the entry.
        assert "kanon add history --catalog-source <git-url>@<ref>" in result.stderr, (
            f"Expected the add-arm replacement for entry 'history', got: {result.stderr!r}"
        )

    def test_flags_only_tail_uses_generic_add_arm(self) -> None:
        result = _run_kanon("bootstrap", "--marketplace-install")
        assert result.returncode == 3
        assert "kanon add <entry> --catalog-source <git-url>@<ref>" in result.stderr, (
            f"Expected the generic add-arm replacement, got: {result.stderr!r}"
        )


@pytest.mark.functional
class TestBootstrapShimChannelDiscipline:
    """The shim never emits a traceback and writes only to stderr, never stdout."""

    @pytest.mark.parametrize("entry", ["kanon", "does-not-exist", "no-such-pkg"])
    def test_any_entry_exits_3(self, entry: str) -> None:
        result = _run_kanon("bootstrap", entry)
        assert result.returncode == 3, (
            f"Expected exit 3 for 'kanon bootstrap {entry}', got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_no_traceback_on_stderr(self) -> None:
        result = _run_kanon("bootstrap", "kanon")
        assert "Traceback" not in result.stderr, f"Unexpected traceback in stderr: {result.stderr!r}"

    def test_docs_link_present(self) -> None:
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert "docs/migration-bootstrap-to-add.md" in result.stderr, (
            f"Expected migration docs link in stderr, got: {result.stderr!r}"
        )

    def test_nothing_on_stdout(self) -> None:
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"
