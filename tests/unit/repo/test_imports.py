"""Import smoke tests for all 53 kanon_cli.repo modules.

Each test attempts to import a specific module from the kanon_cli.repo package.
All tests are marked xfail because the copied source files still use their
original relative imports (e.g., ``import command`` instead of
``from kanon_cli.repo import command``). These tests define the target state
for Sprint 2: every module must be importable from the kanon_cli.repo namespace.
"""

import importlib

import pytest

ROOT_MODULES = [
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
]

SUBCMD_MODULES = [
    "subcmds",
    "subcmds.abandon",
    "subcmds.branches",
    "subcmds.checkout",
    "subcmds.cherry_pick",
    "subcmds.diff",
    "subcmds.diffmanifests",
    "subcmds.download",
    "subcmds.envsubst",
    "subcmds.forall",
    "subcmds.gc",
    "subcmds.grep",
    "subcmds.help",
    "subcmds.info",
    "subcmds.init",
    "subcmds.list",
    "subcmds.manifest",
    "subcmds.overview",
    "subcmds.prune",
    "subcmds.rebase",
    "subcmds.selfupdate",
    "subcmds.smartsync",
    "subcmds.stage",
    "subcmds.start",
    "subcmds.status",
    "subcmds.sync",
    "subcmds.upload",
    "subcmds.version",
]


@pytest.mark.unit
@pytest.mark.xfail(reason="imports not yet fixed -- Sprint 2 T3/T4/T5 will resolve broken relative imports")
@pytest.mark.parametrize("module_suffix", ROOT_MODULES)
def test_root_module_import(module_suffix: str) -> None:
    """Verify kanon_cli.repo.<module> is importable for each root module.

    Args:
        module_suffix: The module name relative to the kanon_cli.repo package.
    """
    full_name = f"kanon_cli.repo.{module_suffix}"
    module = importlib.import_module(full_name)
    assert module is not None, f"importlib.import_module({full_name!r}) returned None"
    assert module.__name__ == full_name, f"Expected module.__name__ to be {full_name!r} but got {module.__name__!r}"


@pytest.mark.unit
@pytest.mark.xfail(reason="imports not yet fixed -- Sprint 2 T2/T3/T4/T5 will resolve broken relative imports")
@pytest.mark.parametrize("module_suffix", SUBCMD_MODULES)
def test_subcmd_module_import(module_suffix: str) -> None:
    """Verify kanon_cli.repo.<module> is importable for each subcmd module.

    Args:
        module_suffix: The module path relative to the kanon_cli.repo package
            (e.g., ``subcmds`` or ``subcmds.abandon``).
    """
    full_name = f"kanon_cli.repo.{module_suffix}"
    module = importlib.import_module(full_name)
    assert module is not None, f"importlib.import_module({full_name!r}) returned None"
    assert module.__name__ == full_name, f"Expected module.__name__ to be {full_name!r} but got {module.__name__!r}"
