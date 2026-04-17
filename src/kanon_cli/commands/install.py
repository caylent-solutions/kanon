"""Install subcommand: parse .kanon config and run core install lifecycle.

Parses the .kanon configuration file and delegates to the core install logic.
No pipx or external tool management is performed.
"""

import pathlib
import sys

from kanon_cli.core.discover import find_kanonenv
from kanon_cli.core.install import install


def register(subparsers) -> None:
    """Register the install subcommand.

    Args:
        subparsers: The subparsers object from the parent parser.
    """
    parser = subparsers.add_parser(
        "install",
        help="Full install lifecycle: multi-source manifest sync and marketplace setup",
        description=(
            "Execute the full Kanon install lifecycle.\n\n"
            "Parses the .kanon configuration file, then runs repo init/envsubst/sync\n"
            "for each source defined in the .kanon file. Aggregates packages into\n"
            ".packages/ via symlinks."
        ),
        epilog="Example:\n  kanon install           # auto-discovers .kanon\n  kanon install .kanon    # explicit path",
        formatter_class=__import__("argparse").RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "kanonenv_path",
        nargs="?",
        default=None,
        type=pathlib.Path,
        help="Path to the .kanon configuration file (default: auto-discover from current directory)",
    )
    parser.set_defaults(func=_run)


def _run(args) -> None:
    """Execute the install command.

    Resolves the .kanon path (walking up from cwd when not provided), parses
    and validates the configuration, then delegates to core.install().

    Parse/validate failures are converted to a non-zero exit with a clear
    stderr message so the CLI boundary preserves fail-fast semantics.

    Args:
        args: Parsed arguments with kanonenv_path.
    """
    from kanon_cli.core.kanonenv import parse_kanonenv

    if args.kanonenv_path is None:
        try:
            args.kanonenv_path = find_kanonenv()
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"kanon install: found {args.kanonenv_path}")

    # The downstream repo manifest parser enforces an absolute `manifest_file`
    # at src/kanon_cli/repo/manifest_xml.py:410. Resolve here at the CLI
    # boundary so `kanon install .kanon` (relative argument) behaves identically
    # to auto-discovery, and fail-fast with a clear message if the file is
    # missing.
    args.kanonenv_path = args.kanonenv_path.resolve()
    if not args.kanonenv_path.is_file():
        print(f"Error: .kanon file not found: {args.kanonenv_path}", file=sys.stderr)
        sys.exit(1)

    try:
        parse_kanonenv(args.kanonenv_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    install(args.kanonenv_path)
