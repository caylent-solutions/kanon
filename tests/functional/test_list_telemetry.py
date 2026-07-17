"""Functional telemetry tests for ``kanon list``.

Proves the ``list`` command participates in the usage-telemetry OTLP emission
workflow like every other command: the detached POST is force-enabled and the
collector endpoint is pointed at an unreachable host so nothing leaves the
machine, and ``--telemetry-debug`` surfaces the exact would-send OTLP JSON on
stderr. Asserts the flat body carries ``tool == "kanon"`` and the payload's
invocation records ``command == "list"`` with the ``--tree`` flag captured by
name and the ``--format`` / ``--status`` values captured by the allowlist --
and that ``KANON_TELEMETRY_DISABLED`` suppresses the whole thing.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from tests.scenarios.conftest import run_kanon


_UNREACHABLE_ENDPOINT = "https://kanon-telemetry.invalid/v1/logs"
_FORCE_ENV = {
    "KANON_TELEMETRY_FORCE": "1",
    "KANON_TELEMETRY_ENDPOINT": _UNREACHABLE_ENDPOINT,
    "KANON_SKIP_UPDATE_CHECK": "1",
    "NO_COLOR": "1",
}


@pytest.fixture()
def project(tmp_path: pathlib.Path) -> pathlib.Path:
    """A project declaring one source (no lock -- list still emits telemetry)."""
    (tmp_path / ".kanon").write_text(
        "GITBASE=https://github.com/acme\n"
        "KANON_SOURCE_foo_URL=https://github.com/acme/foo\n"
        "KANON_SOURCE_foo_REF=1.0.0\nKANON_SOURCE_foo_PATH=vendor/foo\nKANON_SOURCE_foo_NAME=foo\n"
    )
    return tmp_path


def _record_body(stderr: str) -> dict:
    """Extract and parse the flat collector body from the OTLP debug JSON on stderr."""
    start = stderr.index("{")
    end = stderr.rindex("}")
    otlp = json.loads(stderr[start : end + 1])
    body_str = otlp["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"]["stringValue"]
    return json.loads(body_str)


@pytest.mark.functional
class TestListTelemetry:
    """The list command emits well-formed, allowlisted usage telemetry."""

    def test_list_emits_expected_invocation(self, project: pathlib.Path) -> None:
        """--telemetry-debug surfaces command=list with the flag names and allowlisted values."""
        result = run_kanon(
            "--telemetry-debug",
            "list",
            "--tree",
            "--status",
            "orphan",
            "--format",
            "json",
            cwd=project,
            extra_env=_FORCE_ENV,
        )
        assert result.returncode == 0
        body = _record_body(result.stderr)
        assert body["tool"] == "kanon"
        assert body["event_type"] == "cli_command"

        payload = json.loads(body["payload"])
        invocation = payload["invocation"]
        assert invocation["command"] == "list"
        assert "tree" in invocation["flags"]
        assert invocation["flag_values"]["format"] == "json"
        assert invocation["flag_values"]["status"] == "orphan"
        assert payload["outcome"]["status"] == "ok"
        assert payload["outcome"]["exit_code"] == 0
        assert "install_graph" not in payload

    def test_declared_flag_captured_by_name(self, project: pathlib.Path) -> None:
        """The boolean --declared flag is captured by name, not value."""
        result = run_kanon("--telemetry-debug", "list", "--declared", cwd=project, extra_env=_FORCE_ENV)
        assert result.returncode == 0
        payload = json.loads(_record_body(result.stderr)["payload"])
        assert "declared" in payload["invocation"]["flags"]
        assert "declared" not in payload["invocation"]["flag_values"]

    def test_no_secret_or_path_in_payload(self, project: pathlib.Path) -> None:
        """The emitted body never carries the source URL, a file path, or raw argv."""
        result = run_kanon(
            "--telemetry-debug", "list", "--kanon-file", str(project / ".kanon"), cwd=project, extra_env=_FORCE_ENV
        )
        assert result.returncode == 0
        body_text = json.dumps(_record_body(result.stderr))
        assert "github.com/acme/foo" not in body_text
        assert str(project) not in body_text
        assert "--kanon-file" not in body_text

    def test_disabled_suppresses_emission(self, project: pathlib.Path) -> None:
        """KANON_TELEMETRY_DISABLED suppresses emission even with --telemetry-debug."""
        result = run_kanon(
            "--telemetry-debug",
            "list",
            cwd=project,
            extra_env={**_FORCE_ENV, "KANON_TELEMETRY_DISABLED": "1"},
        )
        assert result.returncode == 0
        assert "resourceLogs" not in result.stderr

    def test_unreachable_collector_never_blocks(self, project: pathlib.Path) -> None:
        """Without debug, an unreachable collector never fails the command or leaks JSON."""
        result = run_kanon("list", cwd=project, extra_env=_FORCE_ENV)
        assert result.returncode == 0
        assert "resourceLogs" not in result.stdout
        assert "resourceLogs" not in result.stderr
