"""Unit tests for kanon_cli.completions.preamble."""

from __future__ import annotations

import pytest

from kanon_cli.completions.preamble import PREAMBLE


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
