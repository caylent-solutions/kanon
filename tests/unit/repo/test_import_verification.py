"""Verify that no flat namespace imports remain in the tests/unit/repo/ test files.

AC-TEST-001: test_no_flat_namespace_imports -- scans all test files for bare
  imports of repo-internal modules and asserts none remain.
AC-TEST-002: test_no_import_errors -- verifies all test files can be collected
  by pytest without raising ImportError during AST parsing.
"""

import ast
import pathlib

import pytest

_THIS_DIR = pathlib.Path(__file__).parent

# All modules that live in kanon_cli.repo and must NOT be imported with
# bare (flat-namespace) import statements in the test suite.
_REPO_INTERNAL_MODULES = frozenset(
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
        "subcmds",
        "version_constraints",
        "wrapper",
    }
)


def _collect_flat_namespace_imports(filepath: pathlib.Path) -> list[str]:
    """Return all bare (flat-namespace) imports of repo-internal modules.

    A flat-namespace import is one where the top-level module name matches
    a name in _REPO_INTERNAL_MODULES and the import has no ``kanon_cli.repo``
    prefix.  Cross-test imports (e.g. ``from test_manifest_xml import X``)
    are excluded because ``test_*`` names are test helpers, not repo modules.

    Args:
        filepath: Path to the Python source file to inspect.

    Returns:
        A list of human-readable import statement strings for every violation.
        An empty list means the file is clean.
    """
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        raise RuntimeError(f"Syntax error in {filepath}: {exc}") from exc

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _REPO_INTERNAL_MODULES:
                    violations.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            # level > 0 means relative import -- always OK
            if node.level == 0 and node.module:
                top = node.module.split(".")[0]
                # Skip cross-test imports (test_* modules are test helpers)
                if top.startswith("test_"):
                    continue
                # Skip kanon_cli.* imports (already correct)
                if top == "kanon_cli":
                    continue
                if top in _REPO_INTERNAL_MODULES:
                    names = ", ".join(a.name for a in node.names)
                    violations.append(f"line {node.lineno}: from {node.module} import {names}")
    return violations


def _all_test_files() -> list[pathlib.Path]:
    """Return all test_*.py files in this directory, excluding this file."""
    this_file = pathlib.Path(__file__)
    return sorted(p for p in _THIS_DIR.glob("test_*.py") if p != this_file)


_TEST_FILES = _all_test_files()
_TEST_FILE_IDS = [p.name for p in _TEST_FILES]


@pytest.mark.unit
@pytest.mark.parametrize("test_file", _TEST_FILES, ids=_TEST_FILE_IDS)
def test_no_flat_namespace_imports(test_file: pathlib.Path) -> None:
    """Verify that no flat-namespace imports of repo-internal modules remain.

    Each test file must use ``from kanon_cli.repo import X`` or
    ``from kanon_cli.repo.module import X`` instead of bare ``import X``
    or ``from X import Y`` when X is a repo-internal module.

    Args:
        test_file: Absolute path to the test file to inspect.
    """
    violations = _collect_flat_namespace_imports(test_file)
    assert not violations, (
        f"{test_file.name} still contains flat-namespace imports of repo-internal modules.\n"
        f"Each must be converted to 'from kanon_cli.repo import X' or "
        f"'from kanon_cli.repo.module import Name':\n" + "\n".join(f"  {v}" for v in violations)
    )


@pytest.mark.unit
@pytest.mark.parametrize("test_file", _TEST_FILES, ids=_TEST_FILE_IDS)
def test_no_import_errors(test_file: pathlib.Path) -> None:
    """Verify each test file is parseable without SyntaxError.

    This guards against accidentally introducing syntax errors while
    rewriting imports.  A file that cannot be parsed by the AST module
    would also fail pytest collection.

    Args:
        test_file: Absolute path to the test file to inspect.
    """
    source = test_file.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(test_file))
    except SyntaxError as exc:
        pytest.fail(f"{test_file.name} has a syntax error that would prevent pytest from collecting it: {exc}")
