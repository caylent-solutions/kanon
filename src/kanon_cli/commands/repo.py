"""Repo subcommand: passthrough to kanon's repo subsystem.

Delegates all trailing arguments to repo_run() from the Python API layer.
Supports the full repo subcommand surface (init, sync, envsubst, etc.) by
forwarding arbitrary argv to the repo dispatcher without interpretation.

The repo directory is resolved using documented precedence:

1. ``--repo-dir=<flag>`` wins when present.
2. ``KANON_REPO_DIR`` env var is used when the flag is absent.
3. Falls back to the compiled-in default when neither is set.
"""

import argparse
import os
import sys
from typing import Optional

from kanon_cli.constants import KANON_REPO_DIR_ENV, KANONENV_REPO_DIR_DEFAULT
from kanon_cli.repo import RepoCommandError, repo_run


def resolve_repo_dir(
    flag_value: Optional[str],
    env: Optional[dict] = None,
) -> str:
    """Resolve the repo directory using documented flag-wins-over-env precedence.

    Applies the following resolution order, then converts the result to an
    absolute path via :func:`os.path.abspath`:

    1. If ``flag_value`` is not ``None``, use it (flag wins).
    2. If ``KANON_REPO_DIR`` is present in ``env``, use its value.
    3. Use :data:`~kanon_cli.constants.KANONENV_REPO_DIR_DEFAULT`.

    The absolute-path conversion is required because
    :class:`~kanon_cli.repo.manifest_xml.RepoClient` (and its parent
    :class:`~kanon_cli.repo.manifest_xml.XmlManifest`) enforce that the
    derived ``manifest_file`` path is absolute, raising
    :class:`~kanon_cli.repo.error.ManifestParseError` otherwise.

    Args:
        flag_value: The value supplied to ``--repo-dir``, or ``None`` when the
            flag was not provided.
        env: Mapping used for environment-variable lookup. When ``None``,
            :data:`os.environ` is used. Pass an explicit dict in unit tests to
            avoid reading the real process environment.

    Returns:
        The resolved absolute path to the ``.repo`` directory.
    """
    if env is None:
        env = os.environ
    if flag_value is not None:
        return os.path.abspath(flag_value)
    return os.path.abspath(env.get(KANON_REPO_DIR_ENV, KANONENV_REPO_DIR_DEFAULT))


def register(subparsers) -> None:
    """Register the repo subcommand.

    Adds a ``repo`` sub-parser that captures all trailing arguments using
    argparse.REMAINDER and passes them to the repo dispatcher.

    Args:
        subparsers: The subparsers object from the parent parser.
    """
    parser = subparsers.add_parser(
        "repo",
        help="Run a kanon repo subcommand (manifest-driven sync)",
        description=(
            "Run kanon's repo subcommands.\n\n"
            "All trailing arguments after 'kanon repo' are passed verbatim to\n"
            "the repo dispatcher. Use 'kanon repo --help' to see this help,\n"
            "or 'kanon repo help' to see the per-subcommand help.\n\n"
            "Examples:\n"
            "  kanon repo init -u <url> -b <branch> -m <manifest>\n"
            "  kanon repo sync --jobs=4\n"
            "  kanon repo status\n"
            "  kanon repo help"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo-dir",
        dest="repo_dir",
        default=None,
        help=(
            "Path to the .repo directory for the repo tool "
            f"(default: ${{KANON_REPO_DIR}} or {KANONENV_REPO_DIR_DEFAULT!r})"
        ),
    )
    parser.add_argument(
        "repo_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded verbatim to the repo tool",
    )
    parser.set_defaults(func=_run)


def _run(args) -> None:
    """Execute the repo passthrough command.

    Resolves the repo directory via :func:`resolve_repo_dir`, extracts the
    trailing arguments from ``args.repo_args``, and delegates them to
    repo_run(). Propagates the exit code from repo_run() directly via
    sys.exit().

    Args:
        args: Parsed arguments with repo_args (list of trailing argv) and
            repo_dir (``--repo-dir`` flag value, or ``None`` when not supplied).
    """
    repo_dir = resolve_repo_dir(flag_value=args.repo_dir)
    try:
        exit_code = repo_run(args.repo_args, repo_dir=repo_dir)
    except RepoCommandError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code if exc.exit_code is not None else 1)
    sys.exit(exit_code)
