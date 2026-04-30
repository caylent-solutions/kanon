"""EP (Entry Point) scenarios from `docs/integration-testing.md` §13.

- EP-01: `python -m kanon_cli --version`
- EP-02: `python -m kanon_cli --help`
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest


@pytest.mark.scenario
class TestEP:
    def test_ep_01_python_m_version(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert re.search(r"kanon \d+\.\d+\.\d+", result.stdout), (
            f"stdout does not match `kanon X.Y.Z`: {result.stdout!r}"
        )

    def test_ep_02_python_m_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        for token in ("install", "clean", "validate", "bootstrap"):
            assert token in result.stdout, f"missing {token!r} in stdout"
