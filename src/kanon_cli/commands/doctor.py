"""kanon doctor subcommand: workspace health checks and cache refresh.

Performs workspace health checks and optionally refreshes the completion cache.
The --refresh-completion-cache flag mutates completion-cache files and is
protected by the workspace lock to prevent concurrent cache refreshes from
clobbering each other.

Spec reference: ``spec/kanon-list-add-lock-features-spec.md``
Section 7.5 (Concurrency and atomicity) -- lock extension to
``kanon doctor --refresh-completion-cache``.
"""

import argparse
import pathlib
import sys

from kanon_cli.constants import KANON_COMPLETION_CACHE_DIR, KANON_KANON_FILE_DEFAULT, KANON_KANON_FILE_ENV
from kanon_cli.utils.concurrency import kanon_workspace_lock


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'doctor' subcommand on the top-level argparse subparsers.

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "doctor",
        help="Workspace health checks and cache management.",
        description=(
            "Run workspace health checks against the current project directory.\n\n"
            "With --refresh-completion-cache, refreshes the shell completion cache\n"
            "files under .kanon-data/. This mutation is protected by the workspace\n"
            "lock to prevent concurrent refreshes from producing inconsistent state."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--kanon-file",
        dest="kanon_file",
        default=None,
        metavar="<path>",
        help=(
            f"Path to the .kanon file that identifies the workspace root. "
            f"Defaults to '{KANON_KANON_FILE_DEFAULT}'. "
            f"Overridden by the {KANON_KANON_FILE_ENV} environment variable; "
            "the CLI flag takes precedence when both are set."
        ),
    )

    parser.add_argument(
        "--refresh-completion-cache",
        dest="refresh_completion_cache",
        action="store_true",
        default=False,
        help=(
            "Refresh the shell completion cache files stored under .kanon-data/. "
            "Acquires the workspace exclusive lock before writing, so concurrent "
            "cache refreshes are serialised."
        ),
    )

    parser.set_defaults(func=run_doctor)


def run_doctor(args: argparse.Namespace) -> int:
    """Entry-point function for the 'kanon doctor' subcommand.

    When --refresh-completion-cache is set, acquires the workspace exclusive
    lock (via kanon_workspace_lock) before mutating any completion-cache files.
    This prevents two concurrent refreshes from clobbering each other.

    Args:
        args: Parsed argument namespace from argparse.

    Returns:
        0 on success; non-zero on failure (typically via sys.exit()).
    """
    import os

    kanon_file_str = getattr(args, "kanon_file", None) or os.environ.get(KANON_KANON_FILE_ENV)
    if kanon_file_str is None:
        kanon_file_str = KANON_KANON_FILE_DEFAULT

    kanon_file = pathlib.Path(kanon_file_str)
    workspace_root = kanon_file.resolve().parent

    refresh_completion_cache: bool = getattr(args, "refresh_completion_cache", False)

    if refresh_completion_cache:
        with kanon_workspace_lock(workspace_root):
            _refresh_completion_cache(workspace_root)
        return 0

    # No flags -- run basic health checks (no mutations, no lock needed).
    _run_health_checks(workspace_root)
    return 0


def _refresh_completion_cache(workspace_root: pathlib.Path) -> None:
    """Refresh completion-cache files under .kanon-data/.

    Called exclusively from within a kanon_workspace_lock context, so callers
    hold the workspace exclusive lock and no concurrent mutation can occur.

    Args:
        workspace_root: The project root directory (parent of .kanon).
    """
    cache_dir = workspace_root / ".kanon-data" / KANON_COMPLETION_CACHE_DIR
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"ERROR: Cannot create completion-cache directory {cache_dir}: {exc.strerror}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"kanon doctor: completion cache refreshed at {cache_dir}")


def _run_health_checks(workspace_root: pathlib.Path) -> None:
    """Run non-mutating workspace health checks and print a summary to stdout.

    Args:
        workspace_root: The project root directory (parent of .kanon).
    """
    kanon_file = workspace_root / ".kanon"
    if not kanon_file.exists():
        print(
            f"ERROR: no .kanon file found at {kanon_file}; this does not appear to be a kanon workspace.",
            file=sys.stderr,
        )
        sys.exit(1)

    kanon_data = workspace_root / ".kanon-data"
    if kanon_data.is_dir():
        print(f"kanon doctor: .kanon-data/ exists at {kanon_data}")
    else:
        print(f"kanon doctor: .kanon-data/ not yet created at {kanon_data} (run kanon install first)")

    print("kanon doctor: workspace OK")
