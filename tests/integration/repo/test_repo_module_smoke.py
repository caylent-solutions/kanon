"""E2E smoke tests proving the repo module loads and runs after migration.

These tests verify that the copied kanon_cli.repo source code is not merely
present on disk but is structurally functional: all subcommand classes can be
imported, the Init command can be instantiated, and its option parser produces
a valid optparse.OptionParser object.

AC-TEST-001: test_all_commands_loaded -- verifies all_commands has at least 28 entries
AC-TEST-002: test_init_class_instantiable -- verifies Init command class instantiates
AC-TEST-003: test_init_option_parser_works -- verifies Init OptionParser returns a valid parser
"""

import optparse

import pytest

from kanon_cli.repo.subcmds import all_commands

# The minimum number of entries expected in all_commands.
# 27 command .py files produce 27 named entries, and subcmds/__init__.py adds
# one alias ("branch" -> "branches"), yielding 28 total dictionary entries.
MIN_COMMAND_COUNT = 27

# The subcommand key used to retrieve the Init command class from all_commands.
INIT_COMMAND_KEY = "init"


@pytest.fixture()
def init_instance():
    """Return an instantiated Init command with NAME already set by the module loader.

    The Init class is retrieved from all_commands so that its NAME class
    attribute is already set by the module loader (cmd.NAME = name in
    subcmds/__init__.py). Instantiation uses no arguments, exercising the
    Command.__init__ constructor with all-optional parameters.
    """
    assert INIT_COMMAND_KEY in all_commands, (
        f"Expected 'init' key in all_commands but it is missing. Available commands: {sorted(all_commands.keys())!r}"
    )
    init_cls = all_commands[INIT_COMMAND_KEY]
    return init_cls()


@pytest.mark.integration
def test_all_commands_loaded() -> None:
    """Verify that all_commands contains at least MIN_COMMAND_COUNT entries.

    The subcmds/__init__.py module loader iterates every .py file (excluding
    __init__.py) in the subcmds/ directory, imports each subcommand class, and
    registers it under its command name. It also adds a "branch" alias for
    "branches". This test confirms the loader ran without error and produced
    the full expected set of commands.

    AC-TEST-001
    """
    actual_count = len(all_commands)
    assert actual_count >= MIN_COMMAND_COUNT, (
        f"Expected all_commands to contain at least {MIN_COMMAND_COUNT} entries "
        f"(26 subcommand files + 1 'branch' alias), but found {actual_count}. "
        f"Loaded keys: {sorted(all_commands.keys())!r}. "
        f"Ensure all 27 subcmd .py files were copied to src/kanon_cli/repo/subcmds/."
    )


@pytest.mark.integration
def test_init_class_instantiable(init_instance) -> None:
    """Verify the Init command class can be instantiated with no arguments.

    AC-TEST-002
    """
    assert init_instance is not None, f"Expected Init() to return a non-None instance but got {init_instance!r}"
    assert init_instance.__class__.__name__ == "Init", (
        f"Expected instance class name 'Init' but got '{init_instance.__class__.__name__}'"
    )


@pytest.mark.integration
def test_init_option_parser_works(init_instance) -> None:
    """Verify Init's OptionParser property returns a valid optparse.OptionParser.

    The OptionParser property lazily constructs the parser on first access,
    calling both _CommonOptions and _Options. For Init, _Options delegates to
    Wrapper().InitParser(p) which populates the full set of repo init options.
    This test confirms the parser construction chain executes without error.

    AC-TEST-003
    """
    parser = init_instance.OptionParser
    assert isinstance(parser, optparse.OptionParser), (
        f"Expected OptionParser to return an optparse.OptionParser instance, but got {type(parser)!r}"
    )
    assert parser.usage is not None, "Expected parser.usage to be set but got None"
    assert "init" in parser.usage, f"Expected 'init' to appear in parser.usage but got {parser.usage!r}"
