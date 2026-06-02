"""Unit tests for the uniform `kanon bootstrap` deprecation output.

Every `kanon bootstrap ...` invocation -- any args, any flags, including
`--help` and unknown flags -- prints one comprehensive deprecation message to
stderr and exits non-zero (3). These tests cover the two pure helpers that back
that behavior:

- ``select_bootstrap_tail(argv)`` -- returns the positional tail after the
  ``bootstrap`` subcommand (skipping global flags), or ``None`` when the
  resolved subcommand is not ``bootstrap``.
- ``build_deprecation_message(tail)`` -- renders the message, with a
  per-arm "closest replacement" line derived from the first positional.
"""

import pytest

from kanon_cli.commands.bootstrap import (
    build_deprecation_message,
    select_bootstrap_tail,
)
from kanon_cli.constants import EXIT_CODE_DEPRECATED


@pytest.mark.unit
class TestSelectBootstrapTail:
    """``select_bootstrap_tail`` resolves the bootstrap subcommand from argv."""

    @pytest.mark.parametrize(
        "argv,expected",
        [
            (["bootstrap"], []),
            (["bootstrap", "history"], ["history"]),
            (["bootstrap", "list"], ["list"]),
            # global store-true flags before the subcommand are skipped
            (["--verbose", "bootstrap", "list"], ["list"]),
            (["--no-color", "bootstrap", "history"], ["history"]),
            # flags after the entry are preserved in the tail (positional filtering
            # happens in build_deprecation_message, not here)
            (["bootstrap", "history", "--marketplace-install"], ["history", "--marketplace-install"]),
            (["bootstrap", "--help"], ["--help"]),
        ],
    )
    def test_returns_tail_when_bootstrap_is_subcommand(self, argv, expected):
        assert select_bootstrap_tail(argv) == expected

    @pytest.mark.parametrize(
        "argv",
        [
            [],
            ["install"],
            ["add", "history"],
            ["--help"],
            ["--version"],
            ["list"],  # the top-level `list` command, NOT `bootstrap list`
        ],
    )
    def test_returns_none_when_subcommand_is_not_bootstrap(self, argv):
        assert select_bootstrap_tail(argv) is None


@pytest.mark.unit
class TestBuildDeprecationMessage:
    """``build_deprecation_message`` renders the uniform deprecation text."""

    @pytest.mark.parametrize(
        "tail",
        [[], ["history"], ["list"], ["history", "--marketplace-install"], ["--help"]],
    )
    def test_contains_core_content_for_every_variant(self, tail):
        msg = build_deprecation_message(tail)
        assert "DEPRECATED" in msg
        assert "major release" in msg
        assert "breaking change" in msg
        # the new catalog model, framed generically (not *-marketplace.xml)
        assert "repo-specs" in msg
        assert "<catalog-metadata>" in msg
        assert "*-marketplace.xml" not in msg
        # the search/add/install workflow + .kanon creation
        assert "kanon list" in msg
        assert "kanon add" in msg
        assert "kanon install" in msg
        assert ".kanon" in msg
        assert "if absent" in msg
        # related commands + migration pointer
        assert "remove" in msg and "outdated" in msg and "doctor" in msg
        assert "docs/migration-bootstrap-to-add.md" in msg

    def test_add_arm_closest_replacement_uses_entry_name(self):
        msg = build_deprecation_message(["history"])
        assert "kanon add history --catalog-source <git-url>@<ref>" in msg

    def test_list_arm_closest_replacement_uses_kanon_list(self):
        msg = build_deprecation_message(["list"])
        assert "kanon list --catalog-source <git-url>@<ref>" in msg
        assert "kanon add list" not in msg

    def test_flags_only_tail_falls_back_to_generic_entry(self):
        # e.g. `kanon bootstrap --marketplace-install` (no positional entry)
        msg = build_deprecation_message(["--marketplace-install"])
        assert "kanon add <entry> --catalog-source <git-url>@<ref>" in msg

    def test_entry_arm_ignores_trailing_flags_when_choosing_replacement(self):
        msg = build_deprecation_message(["history", "--marketplace-install", "--foo"])
        assert "kanon add history --catalog-source <git-url>@<ref>" in msg


@pytest.mark.unit
def test_exit_code_deprecated_is_nonzero_three():
    assert EXIT_CODE_DEPRECATED == 3
    assert EXIT_CODE_DEPRECATED != 0
