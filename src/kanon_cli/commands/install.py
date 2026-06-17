"""Install subcommand: parse .kanon config and run core install lifecycle.

Parses the .kanon configuration file and delegates to the core install logic.
No pipx or external tool management is performed.
"""

import os
import pathlib
import sys
import warnings

from kanon_cli.constants import KANON_LOCK_FILE as _KANON_LOCK_FILE_ENV
from kanon_cli.core.cli_args import add_catalog_source_arg
from kanon_cli.core.discover import find_kanonenv
from kanon_cli.core.install import InstallError, install
from kanon_cli.repo import RepoCommandError
from kanon_cli.utils.lock_file_path import derive_lock_file_path

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
        add_help=True,
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
    add_catalog_source_arg(parser)

    # --refresh-lock and --refresh-lock-source are mutually exclusive (spec Section 4.7).
    refresh_group = parser.add_mutually_exclusive_group()
    refresh_group.add_argument(
        "--refresh-lock",
        action="store_true",
        default=False,
        help=(
            "Ignore the existing lockfile, re-resolve every transitive version from "
            "scratch, and overwrite .kanon.lock with the new state. "
            "Requires a CLI-supplied or KANON_CATALOG_SOURCE env-var catalog source; "
            "the lockfile fallback is disabled on this path."
        ),
    )
    refresh_group.add_argument(
        "--refresh-lock-source",
        metavar="NAME",
        default=None,
        help=(
            "Re-resolve exactly one top-level source's full chain while preserving "
            "every other source's lockfile entries verbatim. NAME may be a source "
            "name (the KANON_SOURCE_<name> key) or a catalog entry name resolved "
            "via derive_source_name. "
            "Requires a CLI-supplied or KANON_CATALOG_SOURCE env-var catalog source; "
            "the lockfile fallback is disabled on this path."
        ),
    )

    parser.add_argument(
        "--strict-lock",
        action="store_true",
        default=False,
        help=(
            "Upgrade orphaned lock entries to a hard error. An orphaned lock "
            "entry is a source present in .kanon.lock but absent from .kanon "
            "(e.g. after 'kanon remove'). Without this flag, orphaned entries "
            "are pruned and an info-line is emitted per orphan. With this flag, kanon exits with an error "
            "listing every orphaned source. "
            "Remediation: run without --strict-lock to prune, or restore the "
            "missing KANON_SOURCE_<name>_* triples in .kanon."
        ),
    )
    parser.add_argument(
        "--strict-drift",
        action="store_true",
        default=False,
        help=(
            "Upgrade branch drift to a hard error. Branch drift occurs when "
            "the lockfile records a SHA for a branch-shaped source but the "
            "branch's current tip on the remote is a different SHA. Without "
            "this flag, the locked SHA is reused and an info-line is emitted. "
            "With this flag, kanon exits with an error listing every drifted "
            "source. "
            "Remediation: run 'kanon install --refresh-lock-source <source>' "
            "to accept the new branch tip."
        ),
    )

    parser.add_argument(
        "--lock-file",
        metavar="PATH",
        default=None,
        type=pathlib.Path,
        help=(
            "Path to the lock file. Defaults to <kanon-file>.lock (derived from "
            "--kanon-file). The KANON_LOCK_FILE environment variable is consulted "
            "when this flag is absent; the CLI flag takes precedence when both are set."
        ),
    )

    parser.set_defaults(func=_run)


def _run(args) -> int | None:
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

    lock_file_path = derive_lock_file_path(
        args.kanonenv_path,
        args.lock_file,
        os.environ.get(_KANON_LOCK_FILE_ENV),
    )

    try:
        install(
            args.kanonenv_path,
            lock_file_path=lock_file_path,
            catalog_source=args.catalog_source,
            refresh_lock=args.refresh_lock,
            refresh_lock_source=args.refresh_lock_source,
            strict_lock=args.strict_lock,
            strict_drift=args.strict_drift,
        )
    except InstallError as exc:
        # InstallError subclasses already format their message with an "ERROR:"
        # prefix per the spec-canonical error shape (spec Section 4 header).
        # Canonical fixture: tests/fixtures/errors/lockfile-hash-mismatch.txt,
        # lockfile-sha-unreachable.txt, conflict-detected.txt.
        # Spec section: spec/kanon-list-add-lock-features-spec.md Section 6.
        # Covers HermeticInstallCatalogSourceError (a catalog source was supplied to
        # the hermetic install via --catalog-source or KANON_CATALOG_SOURCE).
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, RepoCommandError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    return None
