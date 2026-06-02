"""Bootstrap subcommand: uniform deprecation output.

``kanon bootstrap`` was removed in a major release (a breaking change). It is
retained only so the name resolves to a clear, actionable message instead of an
"unknown command" error.

Every ``kanon bootstrap ...`` invocation -- any args, any flags, including
``--help`` and unknown flags such as ``--marketplace-install`` -- prints one
comprehensive deprecation message to stderr and exits non-zero
(``EXIT_CODE_DEPRECATED`` == 3). No work is performed and no catalog or
filesystem access is made.

The invocation is intercepted in ``kanon_cli.cli.main`` *before* argparse runs
(so ``--help`` is not specially handled and unknown flags do not raise an
argparse error). The argparse subparser registered here is a defensive fallback
that produces the identical output if that intercept is ever bypassed; it also
keeps ``bootstrap`` a known subcommand for introspection/completion.
"""

import argparse
import sys

from kanon_cli.constants import EXIT_CODE_DEPRECATED

# Single source of truth for the deprecation message body. ``{closest}`` is the
# only per-invocation part (the "closest replacement" line, indented two spaces).
_DEPRECATION_TEMPLATE = """\
DEPRECATED: `kanon bootstrap` was removed in a major release (a breaking change).
This command no longer performs any work and exits non-zero.

WHY IT CHANGED
The catalog model changed. A manifest repo no longer has a separate
catalog/<name>/ location, and the kanon wheel no longer bundles a catalog.
The catalog is now the manifest repo itself: each XML manifest under
repo-specs/ that carries a <catalog-metadata> block is a catalog entry,
identified by its <catalog-metadata><name>. (A marketplace is one kind of
entry; other manifest types live under repo-specs/ too.)

MANAGE KANON DEPENDENCIES INSTEAD
  search    kanon list --catalog-source <git-url>@<ref>
            (narrow with a <substring>, --regex, or --match-fields)
  add       kanon add <entry> --catalog-source <git-url>@<ref>
            (writes the entry into .kanon, creating .kanon for you if absent)
  install   kanon install

CLOSEST REPLACEMENT FOR WHAT YOU RAN
{closest}

RELATED COMMANDS
  list  add  remove  install  clean  outdated  why  doctor  validate
  catalog  completion        (run `kanon <command> --help` for details)

See docs/migration-bootstrap-to-add.md."""


def select_bootstrap_tail(argv: list[str]) -> list[str] | None:
    """Return the argv tail after the ``bootstrap`` subcommand, or ``None``.

    The selected subcommand is the first token that is not an option (every
    top-level global flag -- ``-h``/``--help``/``--version``/``--quiet``/
    ``--verbose``/``--no-color`` -- is valueless, so the first non-``-`` token
    is the subcommand). When that token is ``bootstrap`` the function returns
    everything after it (positionals and flags, in original order) so the caller
    can render an accurate "closest replacement" line; otherwise it returns
    ``None``.

    Args:
        argv: The raw argument vector (``sys.argv[1:]``), excluding ``prog``.

    Returns:
        The tail token list when ``bootstrap`` is the resolved subcommand, else
        ``None``.
    """
    positionals = [tok for tok in argv if not tok.startswith("-")]
    if positionals and positionals[0] == "bootstrap":
        return argv[argv.index("bootstrap") + 1 :]
    return None


def _closest_replacement(tail: list[str]) -> str:
    """Render the indented "closest replacement" line for a bootstrap tail.

    Args:
        tail: Tokens after the ``bootstrap`` subcommand (may include flags).

    Returns:
        ``  kanon list ...`` when the first positional is ``list``;
        ``  kanon add <entry> ...`` when a positional entry is present;
        the generic ``  kanon add <entry> ...`` form otherwise.
    """
    positionals = [tok for tok in tail if not tok.startswith("-")]
    if positionals and positionals[0] == "list":
        return "  kanon list --catalog-source <git-url>@<ref>"
    if positionals:
        return f"  kanon add {positionals[0]} --catalog-source <git-url>@<ref>"
    return "  kanon add <entry> --catalog-source <git-url>@<ref>"


def build_deprecation_message(tail: list[str]) -> str:
    """Render the full deprecation message for a ``bootstrap`` invocation.

    Args:
        tail: Tokens after the ``bootstrap`` subcommand (positionals and flags).

    Returns:
        The complete message (no trailing newline); the only per-invocation part
        is the "closest replacement" line derived from ``tail``.
    """
    return _DEPRECATION_TEMPLATE.format(closest=_closest_replacement(tail))


def _run(args: argparse.Namespace) -> int:
    """Defensive fallback: print the deprecation message and return exit 3.

    Reached only if the ``cli.main`` pre-parse intercept is bypassed. Builds the
    message from the REMAINDER-captured tail so the output is identical.

    Args:
        args: Parsed arguments; ``args.argv_tail`` holds the captured tail.

    Returns:
        ``EXIT_CODE_DEPRECATED`` (3).
    """
    print(build_deprecation_message(getattr(args, "argv_tail", [])), file=sys.stderr)
    return EXIT_CODE_DEPRECATED


def register(subparsers) -> None:
    """Register a minimal, permissive ``bootstrap`` subparser (defensive).

    The real handling is the pre-parse intercept in ``kanon_cli.cli.main``. This
    registration only keeps ``bootstrap`` a known subcommand (for completion /
    introspection) and provides an identical fallback. ``add_help=False`` plus a
    ``REMAINDER`` catch-all means it accepts any trailing args/flags without
    argparse interpreting them.

    Args:
        subparsers: The subparsers object from the parent parser.
    """
    parser = subparsers.add_parser(
        "bootstrap",
        add_help=False,
        help="[DEPRECATED] Removed -- use 'kanon add' / 'kanon list'. See docs/migration-bootstrap-to-add.md.",
    )
    parser.add_argument("argv_tail", nargs=argparse.REMAINDER)
    parser.set_defaults(func=_run)
