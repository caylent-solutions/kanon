"""J10 -- update-available alert journey (spec Section 10.4 / FR-29 / AC-55).

Exercises the "update available" alert end to end:

- The alert prints to **stderr** (never stdout) when the cached PyPI version is
  stale relative to the installed version, naming the available version and the
  ``pipx upgrade kanon-cli`` upgrade command.
- The alert is **silent** when the installed version is up to date.
- The check is **skipped** for dev/editable installs, the ``--no-update-check``
  global flag, and ``KANON_SKIP_UPDATE_CHECK=1``.

Two complementary real harnesses are used, both touching only a per-test
``KANON_HOME`` under ``tmp_path`` and never the live PyPI endpoint:

1. A fresh-interpreter subprocess driver (``python -c`` invoking the real
   ``kanon_cli.core.update_check`` module) seeds a real on-disk cache entry and
   asserts the real stderr/stdout split for the stale-alert and silent-when-
   current legs. The network fetch is monkeypatched inside the child so no real
   socket is opened, but the cache I/O, version comparison, alert rendering, and
   stream routing are all the genuine code paths in a separate process.
2. The real ``python -m kanon_cli`` CLI (via the shared ``_run_kanon`` helper)
   for the dev-install / ``--no-update-check`` / ``KANON_SKIP_UPDATE_CHECK=1``
   skip legs: in the test tree kanon is editable-installed, so a real
   ``kanon --version`` invocation must emit no update alert, proving the
   dev-install and explicit skips suppress the alert with zero stdout pollution.

There is no ``skipif`` and no time-based synchronisation anywhere in this module.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import kanon_cli.constants as constants

from .conftest import _run_kanon


_DRIVER = r"""
import argparse
import sys
from unittest.mock import patch

import kanon_cli.constants as constants
from kanon_cli.core import update_check

scenario = sys.argv[1]
installed = sys.argv[2]
cached_latest = sys.argv[3]
# Seed a STALE cache entry: write at epoch 0 and read far in the future so the
# TTL classifier returns STALE (or FRESH when now is small).
seed_now = int(sys.argv[4])
read_now = int(sys.argv[5])

update_check.write_cached_version(cached_latest, now=seed_now)

ns = argparse.Namespace(no_update_check=False)

# fetch must never be reached on a STALE/FRESH hit; if it is, fail loudly so the
# journey catches an accidental foreground network call.
def _boom():
    raise AssertionError("foreground network fetch must not happen on a cache hit")

with (
    patch.object(update_check, "installed_version", return_value=installed),
    patch.object(update_check, "is_editable_install", return_value=False),
    patch.object(update_check, "fetch_latest_version", side_effect=_boom),
    patch.object(update_check, "fork_background_refresh"),
):
    update_check.maybe_alert_update(ns, "install", environ={"NO_COLOR": "1"}, now=read_now)
"""


def _run_driver(
    *,
    kanon_home: Path,
    installed: str,
    cached_latest: str,
    seed_now: int,
    read_now: int,
) -> subprocess.CompletedProcess:
    """Run the update-check driver in a fresh interpreter under ``kanon_home``."""
    env = {
        **_base_env(),
        constants.KANON_HOME_ENV_VAR: str(kanon_home),
    }
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _DRIVER,
            "scenario",
            installed,
            cached_latest,
            str(seed_now),
            str(read_now),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _base_env() -> dict[str, str]:
    """Return a minimal environment that preserves PATH/PYTHONPATH for the child."""
    import os

    env = dict(os.environ)

    env.pop(constants.KANON_SKIP_UPDATE_CHECK_ENV, None)
    return env


@pytest.mark.functional
def test_stale_cache_prints_alert_to_stderr(tmp_path: Path) -> None:
    """A stale cache with a newer version alerts on stderr, naming the upgrade command."""
    home = tmp_path / "home-stale"
    result = _run_driver(
        kanon_home=home,
        installed="1.0.0",
        cached_latest="99.0.0",
        seed_now=0,
        read_now=10_000_000,
    )
    assert result.returncode == 0, f"driver failed: {result.stderr!r}"

    assert "99.0.0" in result.stderr
    assert constants.KANON_UPDATE_UPGRADE_COMMAND in result.stderr
    assert result.stdout == ""


@pytest.mark.functional
def test_current_version_is_silent(tmp_path: Path) -> None:
    """When the installed version equals the cached latest, no alert is emitted."""
    home = tmp_path / "home-current"
    result = _run_driver(
        kanon_home=home,
        installed="2.0.0",
        cached_latest="2.0.0",
        seed_now=0,
        read_now=10,
    )
    assert result.returncode == 0, f"driver failed: {result.stderr!r}"
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.functional
def test_installed_newer_than_cached_is_silent(tmp_path: Path) -> None:
    """When the installed version is newer than the cached latest, no alert is emitted."""
    home = tmp_path / "home-newer"
    result = _run_driver(
        kanon_home=home,
        installed="3.0.0",
        cached_latest="2.0.0",
        seed_now=0,
        read_now=10,
    )
    assert result.returncode == 0, f"driver failed: {result.stderr!r}"
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.functional
def test_dev_install_real_cli_emits_no_update_alert(tmp_path: Path) -> None:
    """The real `kanon --version` (editable-installed test tree) emits no update alert.

    The CLI is run under a fresh KANON_HOME with no seeded cache; because the test
    tree is an editable/dev install, the update check is skipped and stderr never
    mentions the upgrade command. stdout carries only the version banner.
    """
    result = _run_kanon(
        "--version",
        extra_env={constants.KANON_HOME_ENV_VAR: str(tmp_path / "home-dev")},
    )
    assert result.returncode == 0
    assert constants.KANON_UPDATE_UPGRADE_COMMAND not in result.stderr
    assert constants.KANON_UPDATE_UPGRADE_COMMAND not in result.stdout


@pytest.mark.functional
def test_no_update_check_flag_skips_via_real_cli(tmp_path: Path) -> None:
    """`kanon --no-update-check --version` runs cleanly with no update alert (AC-28)."""
    result = _run_kanon(
        "--no-update-check",
        "--version",
        extra_env={constants.KANON_HOME_ENV_VAR: str(tmp_path / "home-flag")},
    )
    assert result.returncode == 0
    assert constants.KANON_UPDATE_UPGRADE_COMMAND not in result.stderr


@pytest.mark.functional
def test_skip_env_var_skips_via_real_cli(tmp_path: Path) -> None:
    """`KANON_SKIP_UPDATE_CHECK=1 kanon --version` runs cleanly with no update alert (AC-28)."""
    result = _run_kanon(
        "--version",
        extra_env={
            constants.KANON_SKIP_UPDATE_CHECK_ENV: "1",
            constants.KANON_HOME_ENV_VAR: str(tmp_path / "home-skip"),
        },
    )
    assert result.returncode == 0
    assert constants.KANON_UPDATE_UPGRADE_COMMAND not in result.stderr


@pytest.mark.functional
def test_help_lists_no_update_check_flag(tmp_path: Path) -> None:
    """`kanon --help` documents the --no-update-check global flag (AC-28 grep target)."""
    result = _run_kanon(
        "--help",
        extra_env={constants.KANON_HOME_ENV_VAR: str(tmp_path / "home-help")},
    )
    assert result.returncode == 0
    assert "--no-update-check" in result.stdout


@pytest.mark.functional
def test_completion_subcommand_skips_update_alert(tmp_path: Path) -> None:
    """A `__complete_*` invocation emits no update alert on stderr.

    Even with a seeded stale cache the completer path must skip the check so
    Tab-completion stdout/stderr stay clean. The cache is seeded on disk first,
    then the real completer subcommand is invoked.
    """
    home = tmp_path / "home-complete"

    seed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "from kanon_cli.core import update_check\n"
                "update_check.write_cached_version('99.0.0', now=0)\n"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**_base_env(), constants.KANON_HOME_ENV_VAR: str(home)},
    )
    assert seed.returncode == 0, f"cache seed failed: {seed.stderr!r}"

    result = _run_kanon(
        "__complete_cached_catalogs",
        "",
        extra_env={constants.KANON_HOME_ENV_VAR: str(home)},
    )
    assert constants.KANON_UPDATE_UPGRADE_COMMAND not in result.stderr
    assert constants.KANON_UPDATE_UPGRADE_COMMAND not in result.stdout
