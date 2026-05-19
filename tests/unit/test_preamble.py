"""Unit tests for kanon_cli.completions.preamble."""

from __future__ import annotations

import pytest

from kanon_cli.completions.preamble import PREAMBLE

# The complete list of helper function names that must appear in both preambles.
_REQUIRED_HELPERS = [
    "_kanon_complete_catalog_entries",
    "_kanon_complete_source_names_in_kanon",
    "_kanon_complete_names_in_lockfile",
    "_kanon_complete_catalog_versions",
    "_kanon_complete_project_versions",
    "_kanon_complete_cached_catalogs",
    "_kanon_complete_add_arg",
]

# The complete list of __complete_* subcommand invocations that must appear.
_REQUIRED_SUBCOMMANDS = [
    "__complete_catalog_entries",
    "__complete_source_names_in_kanon",
    "__complete_names_in_lockfile",
    "__complete_catalog_versions",
    "__complete_project_versions",
    "__complete_cached_catalogs",
]

# Environment variables that must be referenced in both preambles.
_REQUIRED_ENV_VARS = [
    "KANON_COMPLETION_ENABLED",
    "KANON_COMPLETION_TIMEOUT",
]


@pytest.mark.unit
def test_preamble_is_dict() -> None:
    """PREAMBLE must be a dict."""
    assert isinstance(PREAMBLE, dict)


@pytest.mark.unit
def test_preamble_keys_exactly_bash_and_zsh() -> None:
    """PREAMBLE must have exactly the keys 'bash' and 'zsh'."""
    assert set(PREAMBLE.keys()) == {"bash", "zsh"}


@pytest.mark.unit
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_preamble_values_are_str(shell: str) -> None:
    """Each preamble value must be a str instance."""
    assert isinstance(PREAMBLE[shell], str)


@pytest.mark.unit
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_preamble_values_are_non_empty(shell: str) -> None:
    """Each preamble value must be a non-empty string."""
    assert PREAMBLE[shell] != ""


@pytest.mark.unit
@pytest.mark.parametrize("shell", ["bash", "zsh"])
@pytest.mark.parametrize("helper_name", _REQUIRED_HELPERS)
def test_preamble_contains_helper_function(shell: str, helper_name: str) -> None:
    """Each required helper function name must appear in both preambles."""
    assert helper_name in PREAMBLE[shell], f"Helper '{helper_name}' not found in PREAMBLE['{shell}']"


@pytest.mark.unit
@pytest.mark.parametrize("shell", ["bash", "zsh"])
@pytest.mark.parametrize("subcommand", _REQUIRED_SUBCOMMANDS)
def test_preamble_contains_complete_subcommand(shell: str, subcommand: str) -> None:
    """Each __complete_* subcommand invocation must appear in both preambles."""
    assert subcommand in PREAMBLE[shell], f"Subcommand '{subcommand}' not found in PREAMBLE['{shell}']"


@pytest.mark.unit
@pytest.mark.parametrize("shell", ["bash", "zsh"])
@pytest.mark.parametrize("env_var", _REQUIRED_ENV_VARS)
def test_preamble_references_env_var(shell: str, env_var: str) -> None:
    """Both preambles must reference KANON_COMPLETION_ENABLED and KANON_COMPLETION_TIMEOUT."""
    assert env_var in PREAMBLE[shell], f"Env var '{env_var}' not referenced in PREAMBLE['{shell}']"
