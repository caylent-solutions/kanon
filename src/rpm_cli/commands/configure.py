"""Configure subcommand: prereqs + repo install + lifecycle.

Checks that pipx is available, ensures the repo tool is installed
(from PyPI by default, or from a git URL when REPO_URL and REPO_REV
are set), then delegates to the core configure logic.
"""

import json
import pathlib
import shutil
import subprocess
import sys

from rpm_cli.constants import PYPI_REPO_TOOL_PACKAGE
from rpm_cli.core.configure import configure
from rpm_cli.version import resolve_version


def register(subparsers) -> None:
    """Register the configure subcommand.

    Args:
        subparsers: The subparsers object from the parent parser.
    """
    parser = subparsers.add_parser(
        "configure",
        help="Full lifecycle: check prereqs, install repo, multi-source sync",
        description=(
            "Execute the full rpmConfigure lifecycle.\n\n"
            "Checks prerequisites (pipx on PATH), installs the repo tool,\n"
            "then runs repo init/envsubst/sync for each source defined in\n"
            "the .rpmenv file. Aggregates packages into .packages/ via symlinks."
        ),
        epilog="Example:\n  rpm configure .rpmenv",
        formatter_class=__import__("argparse").RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "rpmenv_path",
        type=pathlib.Path,
        help="Path to the .rpmenv configuration file",
    )
    parser.set_defaults(func=_run)


def _run(args) -> None:
    """Execute the configure command.

    Args:
        args: Parsed arguments with rpmenv_path.
    """
    print("rpm configure: checking prerequisites...")
    _check_pipx()

    from rpm_cli.core.rpmenv import parse_rpmenv

    config = parse_rpmenv(args.rpmenv_path)
    globals_dict = config["globals"]

    repo_url = globals_dict.get("REPO_URL", "")
    repo_rev = globals_dict.get("REPO_REV", "")

    if repo_url and repo_rev:
        resolved_rev = resolve_version(repo_url, repo_rev)
        print(f"rpm configure: installing repo tool from git ({resolved_rev})...")
        _install_repo_tool_from_git(repo_url, resolved_rev)
    elif repo_url or repo_rev:
        print(
            "Error: REPO_URL and REPO_REV must both be set or both be omitted.\n"
            "Set both for git override, or omit both to install from PyPI.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        _ensure_repo_tool_from_pypi()

    configure(args.rpmenv_path)


def _check_pipx() -> None:
    """Verify that pipx is available on PATH.

    Raises:
        SystemExit: If pipx is not found.
    """
    if shutil.which("pipx") is None:
        print(
            "Error: pipx is not installed or not on PATH.\n\n"
            "Install pipx before running rpm configure.\n"
            "  - pip: python3 -m pip install --user pipx\n"
            "  - apt: sudo apt install pipx\n"
            "  - brew: brew install pipx\n"
            "After installing: pipx ensurepath",
            file=sys.stderr,
        )
        sys.exit(1)


def _is_repo_tool_installed() -> bool:
    """Check if rpm-git-repo is installed via pipx.

    Returns:
        True if the package is found in pipx list output.

    Raises:
        SystemExit: If pipx list fails or returns unparseable output.
    """
    result = subprocess.run(
        ["pipx", "list", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"Error: pipx list --json failed: {result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(
            f"Error: pipx list --json returned invalid JSON: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    if "venvs" not in data:
        print(
            "Error: pipx list --json output missing 'venvs' key.",
            file=sys.stderr,
        )
        sys.exit(1)

    return PYPI_REPO_TOOL_PACKAGE in data["venvs"]


def _ensure_repo_tool_from_pypi() -> None:
    """Install rpm-git-repo from PyPI if not already installed.

    Raises:
        SystemExit: If pipx install fails.
    """
    if _is_repo_tool_installed():
        print("rpm configure: repo tool already installed, skipping.")
        return

    print(f"rpm configure: installing repo tool from PyPI ({PYPI_REPO_TOOL_PACKAGE})...")
    result = subprocess.run(
        ["pipx", "install", PYPI_REPO_TOOL_PACKAGE],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"Error: Failed to install {PYPI_REPO_TOOL_PACKAGE} via pipx: {result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)


def _install_repo_tool_from_git(repo_url: str, repo_rev: str) -> None:
    """Install the repo tool from a git URL via pipx (override mode).

    Args:
        repo_url: Git URL of the repo tool.
        repo_rev: Resolved version/branch/tag to install.

    Raises:
        SystemExit: If pipx install fails.
    """
    install_spec = f"git+{repo_url}@{repo_rev}"
    result = subprocess.run(
        ["pipx", "install", "--force", install_spec],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"Error: Failed to install repo tool via pipx: {result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)
