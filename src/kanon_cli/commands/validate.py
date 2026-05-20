"""Validate subcommand with xml, marketplace, and metadata sub-subcommands."""

import subprocess
import sys
from pathlib import Path

from kanon_cli.commands.catalog import (
    AuditFinding,
    _check_entry_name_uniqueness,
    _check_metadata,
    _check_source_name_derivation,
    _format_findings,
)
from kanon_cli.core.marketplace_validator import validate_marketplace
from kanon_cli.core.xml_validator import validate_xml


def register(subparsers) -> None:
    """Register the validate subcommand with xml, marketplace, and metadata sub-subcommands.

    Args:
        subparsers: The subparsers object from the parent parser.
    """
    validate_parser = subparsers.add_parser(
        "validate",
        add_help=True,
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
        add_help=True,
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
        add_help=True,
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

    # metadata sub-subcommand
    meta_parser = validate_subs.add_parser(
        "metadata",
        add_help=True,
        help=(
            "Check catalog metadata soft-spots (required/recommended fields, "
            "source-name derivation, entry-name uniqueness) without network access."
        ),
        description=(
            "Check every *-marketplace.xml under repo-specs/ for in-repo soft-spot "
            "violations (spec Section 3.5 rules 1, 2, 3).\n\n"
            "Checks performed:\n"
            "  - Soft-spot 1 (metadata): required fields present and non-empty,\n"
            "    no duplicate child elements, exactly one <catalog-metadata> block.\n"
            "  - Soft-spot 2 (source-name derivation): entry name normalises cleanly\n"
            "    and uses only [a-zA-Z0-9_-] characters.\n"
            "  - Soft-spot 3 (entry-name uniqueness): no two XML files share the\n"
            "    same <catalog-metadata><name> value.\n\n"
            "No network access. Does not clone. Does not call git ls-remote."
        ),
        epilog=(
            "Example:\n"
            "  kanon validate metadata\n"
            "  kanon validate metadata --repo-root /path/to/repo\n"
            "  kanon validate metadata --format json"
        ),
        formatter_class=__import__("argparse").RawDescriptionHelpFormatter,
    )
    meta_parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root directory (default: auto-detect via git rev-parse)",
    )
    meta_parser.add_argument(
        "--format",
        dest="format",
        choices=("text", "json"),
        default="text",
        metavar="{text,json}",
        help=(
            "Output format. 'text' prints one finding per line with ERROR:/WARN:/INFO: "
            "prefix. 'json' prints a single JSON object {\"findings\": [...]}. Default: text."
        ),
    )
    meta_parser.set_defaults(func=_run_metadata)

    validate_parser.set_defaults(func=_run_validate_help)
    validate_parser._validate_subs = validate_subs


def _run_validate_help(args) -> None:
    """Show help when no validate sub-subcommand is given."""
    if args.validate_command is None:
        print(
            "Error: Must specify a validation target: xml, marketplace, or metadata",
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


def validate_metadata_command(args) -> None:
    """Execute catalog metadata validation (soft-spots 1, 2, 3) without network access.

    Runs three in-repo soft-spot checks from spec Section 3.5 against every
    ``*-marketplace.xml`` file under ``<repo_root>/repo-specs/``:

    - Soft-spot 1 (metadata): required fields present, no duplicate child elements,
      exactly one ``<catalog-metadata>`` block per file.
    - Soft-spot 2 (source-name derivation): entry name normalises cleanly via
      ``derive_source_name`` and uses only ``[a-zA-Z0-9_-]`` characters.
    - Soft-spot 3 (entry-name uniqueness): no two files share the same
      ``<catalog-metadata><name>`` value.

    Does NOT call ``git ls-remote``. No network access. No cloning.

    Exit code semantics:
    - Exit 0 if no ERROR-level findings (warnings are acceptable).
    - Exit 1 if any ERROR-level finding is produced.

    Args:
        args: Parsed arguments. Expected attributes:
            repo_root (Path | None): Optional path to the manifest repo root.
            format (str): Output format -- "text" or "json".

    Raises:
        SystemExit: Always. Exit 0 on success (no errors), exit 1 on any error finding.
    """
    repo_root = _resolve_repo_root(args.repo_root)

    findings: list[AuditFinding] = []
    findings.extend(_check_metadata(repo_root))
    findings.extend(_check_source_name_derivation(repo_root))
    findings.extend(_check_entry_name_uniqueness(repo_root))

    formatted = _format_findings(findings, args.format)
    if formatted:
        print(formatted)

    has_error = any(f.kind == "error" for f in findings)
    sys.exit(1 if has_error else 0)


def _run_metadata(args) -> None:
    """Execute catalog metadata validation.

    Args:
        args: Parsed arguments with optional repo_root and format.
    """
    validate_metadata_command(args)
