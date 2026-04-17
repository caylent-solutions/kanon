"""Tests verifying that all subcmd files use relative imports for repo-internal modules.

Each subcmd Python file under src/kanon_cli/repo/subcmds/ must use relative imports
(``from .. import X``, ``from ..module import Name``, or ``from . import X``) when
referencing repo-internal modules.  No bare absolute imports of internal modules are
permitted.
"""

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).parents[3]
SUBCMDS_DIR = REPO_ROOT / "src" / "kanon_cli" / "repo" / "subcmds"

# All root-level modules that live in kanon_cli.repo (not stdlib or third-party)
REPO_INTERNAL_MODULES = frozenset(
    {
        "color",
        "command",
        "editor",
        "error",
        "event_log",
        "fetch",
        "git_command",
        "git_config",
        "git_refs",
        "git_superproject",
        "git_trace2_event_log",
        "git_trace2_event_log_base",
        "hooks",
        "main",
        "manifest_xml",
        "pager",
        "platform_utils",
        "platform_utils_win32",
        "progress",
        "project",
        "repo_logging",
        "repo_trace",
        "ssh",
        "version_constraints",
        "wrapper",
    }
)

# The subcmds package itself is also repo-internal
SUBCMDS_PACKAGE = "subcmds"

SUBCMD_FILENAMES = [
    "__init__.py",
    "abandon.py",
    "branches.py",
    "checkout.py",
    "cherry_pick.py",
    "diff.py",
    "diffmanifests.py",
    "download.py",
    "envsubst.py",
    "forall.py",
    "gc.py",
    "grep.py",
    "help.py",
    "info.py",
    "init.py",
    "list.py",
    "manifest.py",
    "overview.py",
    "prune.py",
    "rebase.py",
    "selfupdate.py",
    "smartsync.py",
    "stage.py",
    "start.py",
    "status.py",
    "sync.py",
    "upload.py",
]


def _collect_bare_internal_imports(filepath: pathlib.Path) -> list[str]:
    """Return a list of bare (non-relative) import statements that reference repo-internal modules.

    Args:
        filepath: Path to the Python source file to analyse.

    Returns:
        List of human-readable import statement strings that are bare references to
        repo-internal modules.  Empty list means the file is clean.
    """
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in REPO_INTERNAL_MODULES:
                    violations.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                top = node.module.split(".")[0]
                if top in REPO_INTERNAL_MODULES:
                    names = ", ".join(a.name for a in node.names)
                    violations.append(f"line {node.lineno}: from {node.module} import {names}")
                elif top == SUBCMDS_PACKAGE:
                    names = ", ".join(a.name for a in node.names)
                    violations.append(f"line {node.lineno}: from {node.module} import {names}")
    return violations


@pytest.mark.unit
@pytest.mark.parametrize("filename", SUBCMD_FILENAMES)
def test_no_bare_internal_imports(filename: str) -> None:
    """Verify that a subcmd file contains no bare imports of repo-internal modules.

    Args:
        filename: The subcmd filename to check (relative to the subcmds directory).
    """
    filepath = SUBCMDS_DIR / filename
    assert filepath.exists(), f"Expected subcmd file does not exist: {filepath}"
    violations = _collect_bare_internal_imports(filepath)
    assert not violations, (
        f"{filename} contains bare (non-relative) imports of repo-internal modules.\n"
        f"Each of the following must be converted to a relative import "
        f"(e.g. 'from .. import X' or 'from ..module import Name'):\n" + "\n".join(f"  {v}" for v in violations)
    )
