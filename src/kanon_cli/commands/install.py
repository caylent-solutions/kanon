"""Install subcommand: parse .kanon config and run core install lifecycle.

Parses the .kanon configuration file and delegates to the core install logic.
No pipx or external tool management is performed.
"""

import os
import pathlib
import sys
import warnings

from kanon_cli.core.discover import find_kanonenv
from kanon_cli.core.install import install
from kanon_cli.repo import RepoCommandError

# Legacy environment variables superseded by the embedded repo tool and --catalog-source.
_LEGACY_REPO_URL_ENV = "REPO_URL"
_LEGACY_REPO_REV_ENV = "REPO_REV"

# Message template for the legacy env-var deprecation notice.  The var_list
# placeholder is filled at call time with the set of legacy variable names.
_LEGACY_ENV_DEPRECATION_MSG = (
    "{var_list} environment variable(s) are deprecated and no longer used by 'kanon install'. "
    "Use --catalog-source to specify a remote catalog source instead."
)


def _warn_if_legacy_env_vars_set() -> None:
    """Emit a single DeprecationWarning if REPO_URL and/or REPO_REV are set.

    The legacy REPO_URL and REPO_REV environment variables are no longer
    used by kanon install. Users should migrate to --catalog-source.
    A single combined warning is emitted when either or both variables are
    present so that CI pipelines configured with -W error::DeprecationWarning
    can detect the stale configuration.

    The same message is also written directly to sys.stderr so that end users
    and CI logs see the migration notice regardless of Python's active warning
    filter (Python suppresses DeprecationWarning by default in subprocess
    contexts without a -W flag).
    """
    repo_url = os.environ.get(_LEGACY_REPO_URL_ENV)
    repo_rev = os.environ.get(_LEGACY_REPO_REV_ENV)

    if not repo_url and not repo_rev:
        return

    set_vars = [v for v, val in ((_LEGACY_REPO_URL_ENV, repo_url), (_LEGACY_REPO_REV_ENV, repo_rev)) if val]
    var_list = " and ".join(set_vars)
    message = _LEGACY_ENV_DEPRECATION_MSG.format(var_list=var_list)
    warnings.warn(
        message,
        DeprecationWarning,
        stacklevel=2,
    )
    print(message, file=sys.stderr)


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

    Emits a DeprecationWarning if the legacy REPO_URL or REPO_REV environment
    variables are set so existing CI workflows receive a clear migration signal.

    Args:
        args: Parsed arguments with kanonenv_path.
    """
    from kanon_cli.core.kanonenv import parse_kanonenv

    _warn_if_legacy_env_vars_set()

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

    try:
        install(args.kanonenv_path)
    except (OSError, ValueError, RepoCommandError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
