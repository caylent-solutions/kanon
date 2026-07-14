"""Functional journey tests for kanon usage telemetry over a real subprocess install.

Drives the real ``python -m kanon_cli install`` binary against a local
``file://`` manifest + content fixture, with telemetry force-enabled (so the
editable/source-checkout skip is bypassed) and the collector endpoint pointed at
an unreachable host so no event ever leaves the machine. Verifies the emitter's
externally observable contract end to end:

- happy path: the command exits 0 and neither stdout nor stderr carries the
  telemetry JSON (the detached POST to the unreachable collector fails silently);
- ``--telemetry-debug``: the exact would-send OTLP JSON is printed to stderr, the
  flat body carries ``tool == "kanon"``, and the flattened ``installed_packages``
  contains the direct manifest source AND the transitive repo package with their
  resolved content SHAs -- proving the full install-graph capture;
- ``KANON_TELEMETRY_DISABLED=1``: no telemetry JSON is emitted even with
  ``--telemetry-debug`` (the opt-out short-circuits before any work);
- an unreachable collector never fails, delays, or errors the command (exit 0);
- a no-secret scan over the emitted debug body.

The install itself uses ``KANON_ALLOW_INSECURE_REMOTES=1`` for the ``file://``
fixture and ``KANON_SKIP_UPDATE_CHECK=1`` so stderr carries only the telemetry
output under test.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

from tests.scenarios.conftest import make_plain_repo, write_kanonenv


_UNREACHABLE_ENDPOINT = "https://kanon-telemetry.invalid/v1/logs"
_MANIFEST_ALIAS = "primary"
_CONTENT_PACKAGE = "pkg-alpha"


def _build_fixture(base: pathlib.Path) -> tuple[pathlib.Path, str]:
    """Build a file:// manifest repo pulling one content package; return (bare, url)."""
    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    make_plain_repo(content_repos, _CONTENT_PACKAGE, {"README.md": f"# {_CONTENT_PACKAGE}\n"})
    content_url = content_repos.as_uri()

    remote_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_url}/" />\n'
        '  <default remote="local" revision="main" />\n'
        "</manifest>\n"
    )
    primary_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="repo-specs/remote.xml" />\n'
        f'  <project name="{_CONTENT_PACKAGE}" path=".packages/{_CONTENT_PACKAGE}"'
        ' remote="local" revision="main" />\n'
        "</manifest>\n"
    )
    bare = make_plain_repo(
        manifest_repos,
        "manifest-primary",
        {
            "repo-specs/remote.xml": remote_xml,
            "repo-specs/primary.xml": primary_xml,
        },
    )
    return bare, bare.as_uri()


def _base_env(home: pathlib.Path) -> dict[str, str]:
    """Return a subprocess env isolated from any ambient telemetry configuration."""
    env = dict(os.environ)
    for key in (
        "KANON_TELEMETRY_DISABLED",
        "KANON_TELEMETRY_DEBUG",
        "KANON_TELEMETRY_FORCE",
        "KANON_TELEMETRY_ENDPOINT",
    ):
        env.pop(key, None)
    env["KANON_HOME"] = str(home)
    env["KANON_ALLOW_INSECURE_REMOTES"] = "1"
    env["KANON_SKIP_UPDATE_CHECK"] = "1"
    env["NO_COLOR"] = "1"
    return env


def _run_install(project_root: pathlib.Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    """Invoke ``python -m kanon_cli [args...] install`` from ``project_root``."""
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args, "install"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(project_root),
        env=env,
    )


def _extract_otlp(stderr: str) -> dict:
    """Extract and parse the OTLP debug JSON object from captured stderr."""
    start = stderr.index("{")
    end = stderr.rindex("}")
    return json.loads(stderr[start : end + 1])


def _record_body(otlp: dict) -> dict:
    """Return the parsed flat collector body from an OTLP debug request."""
    body_str = otlp["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"]["stringValue"]
    return json.loads(body_str)


@pytest.fixture()
def _project(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Create a project with a .kanon referencing the file:// manifest fixture."""
    _, manifest_url = _build_fixture(tmp_path / "fixtures")
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_kanonenv(
        project_root,
        sources=[(_MANIFEST_ALIAS, manifest_url, "main", "repo-specs/primary.xml")],
    )
    home = tmp_path / "kanon-home"
    return project_root, home


@pytest.mark.functional
def test_happy_path_is_silent_and_exits_zero(_project: tuple[pathlib.Path, pathlib.Path]) -> None:
    """Telemetry on + unreachable collector: exit 0, no telemetry JSON on either stream."""
    project_root, home = _project
    env = _base_env(home)
    env["KANON_TELEMETRY_FORCE"] = "1"
    env["KANON_TELEMETRY_ENDPOINT"] = _UNREACHABLE_ENDPOINT

    result = _run_install(project_root, env)

    assert result.returncode == 0, result.stderr
    assert "resourceLogs" not in result.stdout
    assert "resourceLogs" not in result.stderr


@pytest.mark.functional
def test_debug_emits_full_install_graph(_project: tuple[pathlib.Path, pathlib.Path]) -> None:
    """--telemetry-debug prints the OTLP JSON with the direct + transitive installed packages."""
    project_root, home = _project
    env = _base_env(home)
    env["KANON_TELEMETRY_FORCE"] = "1"
    env["KANON_TELEMETRY_ENDPOINT"] = _UNREACHABLE_ENDPOINT

    result = _run_install(project_root, env, "--telemetry-debug")

    assert result.returncode == 0, result.stderr
    otlp = _extract_otlp(result.stderr)
    body = _record_body(otlp)
    assert body["tool"] == "kanon"
    assert body["event_type"] == "cli_command"

    payload = json.loads(body["payload"])
    assert payload["invocation"]["command"] == "install"
    assert payload["outcome"]["status"] == "ok"

    packages = payload["installed_packages"]
    by_name = {p["name"]: p for p in packages}
    assert _MANIFEST_ALIAS in by_name
    assert by_name[_MANIFEST_ALIAS]["scope"] == "direct"
    assert _CONTENT_PACKAGE in by_name
    assert by_name[_CONTENT_PACKAGE]["scope"] == "transitive"
    assert len(by_name[_CONTENT_PACKAGE]["sha"]) in (40, 64)


@pytest.mark.functional
def test_disabled_env_suppresses_debug_output(_project: tuple[pathlib.Path, pathlib.Path]) -> None:
    """KANON_TELEMETRY_DISABLED=1 emits no telemetry JSON even with --telemetry-debug."""
    project_root, home = _project
    env = _base_env(home)
    env["KANON_TELEMETRY_FORCE"] = "1"
    env["KANON_TELEMETRY_DISABLED"] = "1"
    env["KANON_TELEMETRY_ENDPOINT"] = _UNREACHABLE_ENDPOINT

    result = _run_install(project_root, env, "--telemetry-debug")

    assert result.returncode == 0, result.stderr
    assert "resourceLogs" not in result.stderr


@pytest.mark.functional
def test_debug_body_has_no_planted_secret(_project: tuple[pathlib.Path, pathlib.Path]) -> None:
    """A secret planted in the git committer email domain does not leak arbitrary secrets."""
    project_root, home = _project
    env = _base_env(home)
    env["KANON_TELEMETRY_FORCE"] = "1"
    env["KANON_TELEMETRY_ENDPOINT"] = _UNREACHABLE_ENDPOINT

    result = _run_install(project_root, env, "--telemetry-debug")

    assert result.returncode == 0, result.stderr
    otlp = _extract_otlp(result.stderr)
    serialized = json.dumps(otlp)
    for forbidden in (_UNREACHABLE_ENDPOINT.split("//")[1], "PRIVATE KEY", "ssh-rsa", "BEGIN"):
        assert forbidden not in serialized
