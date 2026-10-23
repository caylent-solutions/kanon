"""Real discovery commands fail without an explicit or configured catalog."""

import os
import pathlib
import sys

import pytest

from kanon_cli.constants import CATALOG_SOURCES_ENV_VAR, MISSING_CATALOG_ERROR_TEMPLATE
from tests.conftest import run_owned_subprocess, subprocess_timeout


@pytest.mark.integration
@pytest.mark.parametrize("command", ["search", "add"])
@pytest.mark.parametrize("catalog_sources", [None, "", "   \n\t"])
def test_discovery_without_catalog_fails_before_writing(
    tmp_path: pathlib.Path, command: str, catalog_sources: str | None
) -> None:
    """Unset and blank discovery sets cannot select a built-in repository."""
    env = dict(os.environ)
    env.pop(CATALOG_SOURCES_ENV_VAR, None)
    if catalog_sources is not None:
        env[CATALOG_SOURCES_ENV_VAR] = catalog_sources
    env["KANON_HOME"] = str(tmp_path / "home")
    args = [command, "example"]
    if command == "add":
        args += ["--kanon-file", str(tmp_path / ".kanon")]
    result = run_owned_subprocess(
        [sys.executable, "-m", "kanon_cli", *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=subprocess_timeout(),
    )
    assert result.returncode == 1
    assert MISSING_CATALOG_ERROR_TEMPLATE.format(command=command) in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / ".kanon").exists()
    assert not (tmp_path / ".kanon.lock").exists()
