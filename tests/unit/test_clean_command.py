"""Tests for the clean command handler."""

import pathlib
import types
from unittest.mock import patch

import pytest

from kanon_cli.commands.clean import _run


@pytest.mark.unit
class TestCleanCommand:
    def test_delegates_to_core(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com\nKANON_SOURCE_build_REVISION=main\nKANON_SOURCE_build_PATH=meta.xml\n"
        )
        args = types.SimpleNamespace(kanonenv_path=kanonenv)
        with patch("kanon_cli.commands.clean.clean") as mock_clean:
            _run(args)
            mock_clean.assert_called_once_with(kanonenv)
