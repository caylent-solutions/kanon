"""NS scenarios from `docs/integration-testing.md` §28c -- New 3.0.0 Command Surface.

These scenarios exercise the 3.0.0 command surface end to end against the real
`python -m kanon_cli` CLI: the `kanon marketplace` per-dependency flag manager
(status / enable / disable), the native `kanon completion powershell` generator,
the shared-store `--home` / `--store-dir` global flag, and the
`--no-update-check` / `KANON_SKIP_UPDATE_CHECK` PyPI-check suppression.

Scenarios automated:
- NS-01: `kanon marketplace status` on a `.kanon` with no marketplace deps.
- NS-02: `kanon marketplace enable` rejects a non-marketplace dependency.
- NS-03: `kanon marketplace disable` on an already-disabled alias is a no-op.
- NS-04: `kanon completion powershell` emits a PowerShell script.
- NS-05: `--home` flag overrides `KANON_HOME` for the store root.
- NS-06: `--no-update-check` suppresses the PyPI update check.
- NS-07: `KANON_SKIP_UPDATE_CHECK=1` suppresses the PyPI update check.

NS-06/NS-07 note: in the test tree kanon is editable-installed, so the
update-available alert is already skipped for every invocation via the
dev/editable-install gate (`is_editable_install`). A bare `kanon --version`
therefore could not falsify the suppression -- it stays silent regardless of the
flag. To make the suppression genuinely falsifiable these two scenarios drive the
real `kanon_cli.core.update_check.maybe_alert_update` hook in a fresh interpreter
with the editable gate neutralized and a stale newer-version cache seeded, exactly
as `tests/functional/test_update_alert_journey.py` does. A `control` leg proves the
harness DOES emit the alert; the `--no-update-check` (NS-06) and
`KANON_SKIP_UPDATE_CHECK=1` (NS-07) legs prove each suppression silences it. Each
scenario also asserts the documented real-CLI behaviour (exit 0, version banner,
no upgrade-command pollution) for the literal doc command.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

import kanon_cli.constants as constants

from tests.scenarios.conftest import (
    make_plain_repo,
    run_kanon,
)


_VERSION_BANNER_RE = re.compile(r"kanon \d+\.\d+\.\d+")


def _write_alpha_kanon(target_dir: pathlib.Path, manifest_url: str) -> pathlib.Path:
    """Write a single-source ``.kanon`` (alias ``alpha``) with no marketplace flag.

    The absence of any ``KANON_SOURCE_alpha_MARKETPLACE`` line is the canonical
    disabled/non-marketplace state used by NS-01..NS-03 (spec Section 4.4: an
    absent line and an explicit ``=false`` render identically as disabled).
    """
    kanon_file = target_dir / ".kanon"
    kanon_file.write_text(
        f"KANON_SOURCE_alpha_URL={manifest_url}\n"
        "KANON_SOURCE_alpha_REF=main\n"
        "KANON_SOURCE_alpha_PATH=repo-specs/alpha-only.xml\n"
        "KANON_SOURCE_alpha_NAME=alpha\n"
        "KANON_SOURCE_alpha_GITBASE=https://example.com\n"
    )
    return kanon_file


def _build_alpha_manifest(base: pathlib.Path) -> pathlib.Path:
    """Build a single-source manifest fixture (one package ``pkg-alpha``).

    Returns the bare manifest repo path so callers can derive its ``file://`` URL.
    """
    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    make_plain_repo(content_repos, "pkg-alpha", {"README.md": "# pkg-alpha\n"})
    content_repos_url = content_repos.as_uri()

    remote_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_repos_url}/" />\n'
        '  <default remote="local" revision="main" sync-j="4" />\n'
        "</manifest>\n"
    )
    alpha_only_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="repo-specs/remote.xml" />\n'
        '  <project name="pkg-alpha" path=".packages/pkg-alpha"'
        ' remote="local" revision="main" />\n'
        "</manifest>\n"
    )

    return make_plain_repo(
        manifest_repos,
        "manifest-primary",
        {
            "repo-specs/remote.xml": remote_xml,
            "repo-specs/alpha-only.xml": alpha_only_xml,
        },
    )


_UPDATE_CHECK_DRIVER = r"""
import argparse
import sys
from unittest.mock import patch

import kanon_cli.constants as constants
from kanon_cli.core import update_check

mode = sys.argv[1]

update_check.write_cached_version("99.0.0", now=0)

ns = argparse.Namespace(no_update_check=(mode == "flag"))
environ = {"NO_COLOR": "1"}
if mode == "env":
    environ[constants.KANON_SKIP_UPDATE_CHECK_ENV] = constants.KANON_SKIP_UPDATE_CHECK_TRUE


def _boom():
    raise AssertionError("foreground network fetch must not happen on a cache hit")


with (
    patch.object(update_check, "installed_version", return_value="1.0.0"),
    patch.object(update_check, "is_editable_install", return_value=False),
    patch.object(update_check, "fetch_latest_version", side_effect=_boom),
    patch.object(update_check, "fork_background_refresh"),
):
    update_check.maybe_alert_update(ns, "install", environ=environ, now=10_000_000)
"""


def _run_update_check_driver(mode: str, kanon_home: pathlib.Path) -> subprocess.CompletedProcess:
    """Run the update-check hook in a fresh interpreter under ``kanon_home``.

    ``mode`` selects the suppression leg: ``"control"`` (no suppression),
    ``"flag"`` (``no_update_check=True``, the parsed effect of ``--no-update-check``),
    or ``"env"`` (``KANON_SKIP_UPDATE_CHECK=1`` in the environment). The editable
    gate is patched off and a stale newer-version cache is seeded so the alert
    WOULD fire absent suppression; no real socket is opened.
    """
    env = dict(os.environ)
    env.pop(constants.KANON_SKIP_UPDATE_CHECK_ENV, None)
    env[constants.KANON_HOME_ENV_VAR] = str(kanon_home)
    return subprocess.run(
        [sys.executable, "-c", _UPDATE_CHECK_DRIVER, mode],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.mark.scenario
class TestNSCommandSurface:
    def test_ns_01_marketplace_status_no_marketplace_deps(self, tmp_path: pathlib.Path) -> None:
        """NS-01: marketplace status renders the column headers and a disabled alpha row."""
        manifest_bare = _build_alpha_manifest(tmp_path / "fixtures")
        work_dir = tmp_path / "ns-01"
        work_dir.mkdir()
        kanon_file = _write_alpha_kanon(work_dir, manifest_bare.as_uri())

        result = run_kanon("marketplace", "status", "--kanon-file", str(kanon_file), cwd=work_dir)

        assert result.returncode == 0, (
            f"kanon marketplace status exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        for header in ("ALIAS", "TYPE", "SETTING"):
            assert header in result.stdout, f"Expected column header {header!r} in stdout, got stdout={result.stdout!r}"

        all_result = run_kanon("marketplace", "status", "--all", "--kanon-file", str(kanon_file), cwd=work_dir)
        assert all_result.returncode == 0, (
            f"kanon marketplace status --all exited {all_result.returncode}\n"
            f"stdout={all_result.stdout!r}\nstderr={all_result.stderr!r}"
        )
        alpha_row = [line for line in all_result.stdout.splitlines() if line.startswith("alpha")]
        assert alpha_row, f"Expected an 'alpha' row under --all, got stdout={all_result.stdout!r}"
        assert "disabled" in alpha_row[0], (
            f"Expected the alpha row to render as disabled (no _MARKETPLACE line), got {alpha_row[0]!r}"
        )

    def test_ns_02_marketplace_enable_rejects_non_marketplace_dependency(self, tmp_path: pathlib.Path) -> None:
        """NS-02: enable on a non-marketplace alias exits non-zero with a pretty error."""
        manifest_bare = _build_alpha_manifest(tmp_path / "fixtures")
        work_dir = tmp_path / "ns-02"
        work_dir.mkdir()
        kanon_file = _write_alpha_kanon(work_dir, manifest_bare.as_uri())
        before = kanon_file.read_text()

        result = run_kanon("marketplace", "enable", "alpha", "--kanon-file", str(kanon_file), cwd=work_dir)

        assert result.returncode != 0, (
            f"kanon marketplace enable exited 0 for a non-marketplace alias\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "is not a 'claude-marketplace' type" in result.stderr, (
            f"Expected the non-marketplace-type error in stderr, got stderr={result.stderr!r}"
        )
        assert "KANON_SOURCE_alpha_MARKETPLACE" in result.stderr, (
            f"Expected the error to name KANON_SOURCE_alpha_MARKETPLACE, got stderr={result.stderr!r}"
        )
        assert kanon_file.read_text() == before, (
            "kanon marketplace enable must not modify .kanon when it rejects the alias"
        )

    def test_ns_03_marketplace_disable_already_disabled_is_noop(self, tmp_path: pathlib.Path) -> None:
        """NS-03: disable on an already-disabled alias exits 0 and never writes =false."""
        manifest_bare = _build_alpha_manifest(tmp_path / "fixtures")
        work_dir = tmp_path / "ns-03"
        work_dir.mkdir()
        kanon_file = _write_alpha_kanon(work_dir, manifest_bare.as_uri())
        before = kanon_file.read_text()

        result = run_kanon("marketplace", "disable", "alpha", "--kanon-file", str(kanon_file), cwd=work_dir)

        assert result.returncode == 0, (
            f"kanon marketplace disable exited {result.returncode} on an already-disabled alias\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "already disabled for 'alpha'" in result.stdout, (
            f"Expected 'already disabled for 'alpha'' in stdout, got stdout={result.stdout!r}"
        )
        after = kanon_file.read_text()
        assert after == before, ".kanon must be unchanged after a no-op disable"
        assert "_MARKETPLACE" not in after, "kanon must never write a =false _MARKETPLACE line"

    def test_ns_04_completion_powershell_emits_script(self, tmp_path: pathlib.Path) -> None:
        """NS-04: completion powershell prints a PowerShell script header, exit 0."""
        result = run_kanon("completion", "powershell", cwd=tmp_path)

        assert result.returncode == 0, (
            f"kanon completion powershell exited {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.strip(), "kanon completion powershell produced empty stdout"
        first_line = result.stdout.splitlines()[0]
        assert first_line.startswith("#"), (
            f"Expected the PowerShell script to begin with a comment header, got {first_line!r}"
        )
        assert "completion powershell" in result.stdout, (
            f"Expected the header to mention 'completion powershell', got stdout={result.stdout!r}"
        )
        assert "Invoke-Expression" in result.stdout, (
            f"Expected the header to mention 'Invoke-Expression', got stdout={result.stdout!r}"
        )

    def test_ns_05_home_flag_overrides_kanon_home(self, tmp_path: pathlib.Path) -> None:
        """NS-05: --home relocates the store to the flag path, not the KANON_HOME env path."""
        manifest_bare = _build_alpha_manifest(tmp_path / "fixtures")
        manifest_url = manifest_bare.as_uri()
        work_dir = tmp_path / "ns-05"
        work_dir.mkdir()
        kanon_file = _write_alpha_kanon(work_dir, manifest_url)

        env_home = tmp_path / "env-home"
        flag_home = tmp_path / "flag-home"
        env_home.mkdir()

        extra_env = {
            constants.KANON_HOME_ENV_VAR: str(env_home),
            "KANON_CATALOG_SOURCE": f"{manifest_url}@main",
            "KANON_ALLOW_INSECURE_REMOTES": "1",
        }

        result = run_kanon("--home", str(flag_home), "install", str(kanon_file), cwd=work_dir, extra_env=extra_env)

        assert result.returncode == 0, (
            f"kanon --home install exited {result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        flag_store_packages = flag_home / constants.KANON_HOME_STORE_SUBDIR / ".packages"
        assert flag_store_packages.is_dir(), f"--home store not created under the flag path: {flag_store_packages}"
        env_store = env_home / constants.KANON_HOME_STORE_SUBDIR
        assert not env_store.exists(), (
            f"--home must take precedence over KANON_HOME env, but the env store was created: {env_store}"
        )
        assert not (work_dir / ".packages").exists(), "install must not write artifacts beside .kanon"

        clean_result = run_kanon("--home", str(flag_home), "clean", str(kanon_file), cwd=work_dir)
        assert clean_result.returncode == 0, (
            f"kanon --home clean exited {clean_result.returncode}\n"
            f"stdout={clean_result.stdout!r}\nstderr={clean_result.stderr!r}"
        )

        store_dir_home = tmp_path / "store-dir-home"
        sd_result = run_kanon(
            "--store-dir", str(store_dir_home), "install", str(kanon_file), cwd=work_dir, extra_env=extra_env
        )
        assert sd_result.returncode == 0, (
            f"kanon --store-dir install exited {sd_result.returncode}\n"
            f"stdout={sd_result.stdout!r}\nstderr={sd_result.stderr!r}"
        )
        sd_store_packages = store_dir_home / constants.KANON_HOME_STORE_SUBDIR / ".packages"
        assert sd_store_packages.is_dir(), (
            f"--store-dir (alias for --home) store not created under the flag path: {sd_store_packages}"
        )
        run_kanon("--store-dir", str(store_dir_home), "clean", str(kanon_file), cwd=work_dir)

    def test_ns_06_no_update_check_flag_suppresses_pypi_check(self, tmp_path: pathlib.Path) -> None:
        """NS-06: --no-update-check suppresses the alert the seeded cache would otherwise emit."""
        control = _run_update_check_driver("control", tmp_path / "home-control")
        assert control.returncode == 0, f"control driver failed: {control.stderr!r}"
        assert constants.KANON_UPDATE_UPGRADE_COMMAND in control.stderr, (
            "control leg must emit the update alert so the suppression legs are falsifiable; "
            f"got stderr={control.stderr!r}"
        )

        suppressed = _run_update_check_driver("flag", tmp_path / "home-flag")
        assert suppressed.returncode == 0, f"flag driver failed: {suppressed.stderr!r}"
        assert constants.KANON_UPDATE_UPGRADE_COMMAND not in suppressed.stderr, (
            f"--no-update-check must suppress the update alert, got stderr={suppressed.stderr!r}"
        )
        assert suppressed.stdout == "", f"the update check must never write to stdout, got {suppressed.stdout!r}"

        cli = run_kanon(
            "--no-update-check",
            "--version",
            cwd=tmp_path,
            extra_env={constants.KANON_HOME_ENV_VAR: str(tmp_path / "home-cli")},
        )
        assert cli.returncode == 0, (
            f"kanon --no-update-check --version exited {cli.returncode}\nstdout={cli.stdout!r}\nstderr={cli.stderr!r}"
        )
        assert _VERSION_BANNER_RE.search(cli.stdout), (
            f"Expected a 'kanon X.Y.Z' version banner in stdout, got {cli.stdout!r}"
        )
        assert constants.KANON_UPDATE_UPGRADE_COMMAND not in cli.stderr, (
            f"kanon --no-update-check must emit no update alert, got stderr={cli.stderr!r}"
        )

    def test_ns_07_skip_update_check_env_suppresses_pypi_check(self, tmp_path: pathlib.Path) -> None:
        """NS-07: KANON_SKIP_UPDATE_CHECK=1 suppresses the alert the seeded cache would emit."""
        control = _run_update_check_driver("control", tmp_path / "home-control")
        assert control.returncode == 0, f"control driver failed: {control.stderr!r}"
        assert constants.KANON_UPDATE_UPGRADE_COMMAND in control.stderr, (
            "control leg must emit the update alert so the suppression legs are falsifiable; "
            f"got stderr={control.stderr!r}"
        )

        suppressed = _run_update_check_driver("env", tmp_path / "home-env")
        assert suppressed.returncode == 0, f"env driver failed: {suppressed.stderr!r}"
        assert constants.KANON_UPDATE_UPGRADE_COMMAND not in suppressed.stderr, (
            f"KANON_SKIP_UPDATE_CHECK=1 must suppress the update alert, got stderr={suppressed.stderr!r}"
        )
        assert suppressed.stdout == "", f"the update check must never write to stdout, got {suppressed.stdout!r}"

        cli = run_kanon(
            "--version",
            cwd=tmp_path,
            extra_env={
                constants.KANON_SKIP_UPDATE_CHECK_ENV: constants.KANON_SKIP_UPDATE_CHECK_TRUE,
                constants.KANON_HOME_ENV_VAR: str(tmp_path / "home-cli"),
            },
        )
        assert cli.returncode == 0, (
            f"KANON_SKIP_UPDATE_CHECK=1 kanon --version exited {cli.returncode}\n"
            f"stdout={cli.stdout!r}\nstderr={cli.stderr!r}"
        )
        assert _VERSION_BANNER_RE.search(cli.stdout), (
            f"Expected a 'kanon X.Y.Z' version banner in stdout, got {cli.stdout!r}"
        )
        assert constants.KANON_UPDATE_UPGRADE_COMMAND not in cli.stderr, (
            f"KANON_SKIP_UPDATE_CHECK=1 must emit no update alert, got stderr={cli.stderr!r}"
        )
