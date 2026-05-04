"""Validate subcommand with xml and marketplace sub-subcommands."""

import subprocess
import sys
from pathlib import Path

from kanon_cli.core.marketplace_validator import validate_marketplace
from kanon_cli.core.xml_validator import validate_xml


def register(subparsers) -> None:
    """Register the validate subcommand with xml and marketplace sub-subcommands.

    Args:
        subparsers: The subparsers object from the parent parser.
    """
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate XML manifests",
        description="Validate manifest XML files for well-formedness and correctness.",
    )

    validate_subs = validate_parser.add_subparsers(
        dest="validate_command",
        title="validation targets",
        description="Available validation targets",
    )

    # xml sub-subcommand
    xml_parser = validate_subs.add_parser(
        "xml",
        help="Validate manifest XML files (well-formedness, required attributes, include chains)",
        description=(
            "Validate all XML manifest files under repo-specs/.\n\n"
            "Checks well-formedness, required attributes on <project> and <remote>\n"
            "elements, and that <include> name attributes point to existing files."
        ),
        epilog="Example:\n  kanon validate xml\n  kanon validate xml --repo-root /path/to/repo",
        formatter_class=__import__("argparse").RawDescriptionHelpFormatter,
    )
    xml_parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root directory (default: auto-detect via git rev-parse)",
    )
    xml_parser.set_defaults(func=_run_xml)

    # marketplace sub-subcommand
    mp_parser = validate_subs.add_parser(
        "marketplace",
        help="Validate marketplace XML manifests (linkfile dest, include chains, name uniqueness, tag format)",
        description=(
            "Validate all marketplace XML manifests under repo-specs/.\n\n"
            "Checks linkfile dest attributes, include chain integrity,\n"
            "project path uniqueness, and revision tag format."
        ),
        epilog="Example:\n  kanon validate marketplace\n  kanon validate marketplace --repo-root /path/to/repo",
        formatter_class=__import__("argparse").RawDescriptionHelpFormatter,
    )
    mp_parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root directory (default: auto-detect via git rev-parse)",
    )
    mp_parser.set_defaults(func=_run_marketplace)

    validate_parser.set_defaults(func=_run_validate_help)
    validate_parser._validate_subs = validate_subs


def _run_validate_help(args) -> None:
    """Show help when no validate sub-subcommand is given."""
    if args.validate_command is None:
        print(
            "Error: Must specify a validation target: xml or marketplace",
            file=sys.stderr,
        )
        sys.exit(2)


def _resolve_repo_root(provided: Path | None) -> Path:
    """Resolve repository root from argument or git.

    Args:
        provided: Explicitly provided repo root, or None for auto-detect.

    Returns:
        The resolved repository root path, always absolute.

    Raises:
        SystemExit: If auto-detection fails or the provided directory does not
            exist.
    """
    # Normalize to an absolute path at the CLI boundary so downstream
    # pathlib operations (rglob, relative_to, joinpath) work identically
    # whether the user invoked `kanon validate xml --repo-root .` (relative)
    # or `kanon validate xml --repo-root /abs/path` (absolute) or omitted the
    # flag (auto-detect via `git rev-parse --show-toplevel`, which always
    # produces an absolute path). Fail-fast if an explicit path does not exist.
    if provided is not None:
        resolved = provided.resolve()
        if not resolved.is_dir():
            print(f"Error: --repo-root directory not found: {resolved}", file=sys.stderr)
            sys.exit(1)
        return resolved

    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            "Error: Could not auto-detect repo root. Run from within a git repository or use --repo-root.",
            file=sys.stderr,
        )
        sys.exit(1)

    return Path(result.stdout.strip())


def _run_xml(args) -> None:
    """Execute XML validation.

    Args:
        args: Parsed arguments with optional repo_root.
    """
    repo_root = _resolve_repo_root(args.repo_root)
    exit_code = validate_xml(repo_root)
    sys.exit(exit_code)


def _run_marketplace(args) -> None:
    """Execute marketplace validation.

    Args:
        args: Parsed arguments with optional repo_root.
    """
    repo_root = _resolve_repo_root(args.repo_root)
    exit_code = validate_marketplace(repo_root)
    sys.exit(exit_code)
