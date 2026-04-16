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
        help="Full lifecycle: install repo, multi-source sync",
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

    Parses the .kanon configuration file and calls core.install() directly.
    Emits a deprecation warning to stderr if REPO_URL or REPO_REV are present
    in the globals section (these keys are no longer used).

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

    try:
        config = parse_kanonenv(args.kanonenv_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    globals_dict = config["globals"]

    for deprecated_key in ("REPO_URL", "REPO_REV"):
        if globals_dict.get(deprecated_key):
            print(
                f"Deprecation warning: {deprecated_key} is no longer used by kanon install. "
                f"This key has no effect and will be ignored. "
                f"Remove {deprecated_key} from your .kanon file.",
                file=sys.stderr,
            )

    install(args.kanonenv_path)
