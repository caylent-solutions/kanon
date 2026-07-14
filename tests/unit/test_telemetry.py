"""Unit tests for kanon_cli.core.telemetry (usage-telemetry emitter).

Covers the emitter end to end at the unit level:

- the skip gate (opt-out env var wins; completer subcommands; editable/dev skip;
  the force override for dev/editable);
- credential stripping of every URL shape (https userinfo, token userinfo, ssh,
  scp shorthand) and the host/org/repo split;
- the zero-secret allowlist collection (command/subcommand/boolean-flag NAMES and
  the closed-domain ``format`` value only; never raw argv, paths, targets, or
  free-form string values);
- the runtime environment descriptor and credential-stripped git provenance;
- the full install-graph + flattened installed-packages build from a lockfile,
  including the content-pin-only fallback so no synced package is dropped;
- the flat OTLP-logs body (exactly tool/timestamp/event_type/payload, payload a
  JSON string, tool == "kanon") and the OTLP request wrapper;
- the HTTPS-only POST guard, explicit Content-Type / User-Agent, and body-size
  cap truncation;
- the top-level emit hook: skipped -> no spawn / no output; debug -> exact JSON to
  the injected stream; happy path -> a single detached spawn that POSTs; and the
  never-fail contract (a build error is swallowed, never raised);
- a no-secret matrix scan asserting no planted credential ever appears in any
  serialized body.

Every network / spawn / clock / cwd seam is injected so no test touches the live
collector, the operator's real git config, or forks a real process. All
assertions are real and can fail if the code is wrong.
"""

from __future__ import annotations

import argparse
import io
import json
import platform
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import kanon_cli.constants as constants
from kanon_cli.cli import build_parser
from kanon_cli.core import telemetry
from kanon_cli.core.lockfile import (
    CURRENT_SCHEMA_VERSION,
    ContentPinEntry,
    IncludeEntry,
    Lockfile,
    ProjectEntry,
    SourceEntry,
    write_lockfile,
)


def _args(**overrides: object) -> argparse.Namespace:
    """Build an argparse namespace with defaults for the telemetry flags."""
    ns = argparse.Namespace(
        command=None,
        telemetry_debug=False,
        telemetry_endpoint=None,
        func=lambda a: 0,
        parser=None,
    )
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


@pytest.fixture(autouse=True)
def _isolated_kanon_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point KANON_HOME at a tmp dir so the error log never touches the real store."""
    home = tmp_path / "kanon-home"
    monkeypatch.setenv(constants.KANON_HOME_ENV_VAR, str(home))
    return home


class _FakeResponse:
    """Minimal context-manager stand-in for urllib's response object."""

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, amt: int = -1) -> bytes:
        return b""


def _inline_spawn_capture() -> tuple[list[dict[str, Any]], Any]:
    """Return (calls, spawn_fn) where spawn_fn runs the callable inline and records it."""
    calls: list[dict[str, Any]] = []

    def _spawn(fn: Any, *, log_path: Path) -> None:
        calls.append({"log_path": log_path})
        fn()

    return calls, _spawn


@pytest.mark.unit
def test_should_skip_disabled_env_wins_even_for_wheel_install() -> None:
    """KANON_TELEMETRY_DISABLED truthy skips telemetry regardless of install type."""
    for value in ("1", "true", "YES", "on"):
        assert (
            telemetry.should_skip(
                _args(),
                "install",
                environ={constants.KANON_TELEMETRY_DISABLED_ENV: value},
                editable_probe=lambda: False,
            )
            is True
        )


@pytest.mark.unit
@pytest.mark.parametrize("command", ["__complete_catalog_entries", "__complete_project_versions"])
def test_should_skip_completer_subcommands(command: str) -> None:
    """Every registered __complete_* completer invocation is skipped."""
    assert telemetry.should_skip(_args(), command, environ={}, editable_probe=lambda: False) is True


@pytest.mark.unit
def test_should_skip_editable_install() -> None:
    """A dev/editable install skips telemetry when not force-enabled."""
    assert telemetry.should_skip(_args(), "install", environ={}, editable_probe=lambda: True) is True


@pytest.mark.unit
def test_force_overrides_editable_skip() -> None:
    """KANON_TELEMETRY_FORCE truthy proceeds even on an editable install."""
    assert (
        telemetry.should_skip(
            _args(),
            "install",
            environ={constants.KANON_TELEMETRY_FORCE_ENV: "1"},
            editable_probe=lambda: True,
        )
        is False
    )


@pytest.mark.unit
def test_disabled_wins_over_force() -> None:
    """The opt-out is absolute: DISABLED wins even when FORCE is also set."""
    assert (
        telemetry.should_skip(
            _args(),
            "install",
            environ={
                constants.KANON_TELEMETRY_DISABLED_ENV: "1",
                constants.KANON_TELEMETRY_FORCE_ENV: "1",
            },
            editable_probe=lambda: False,
        )
        is True
    )


@pytest.mark.unit
def test_should_not_skip_normal_wheel_install() -> None:
    """A normal command on a wheel install is not skipped."""
    assert telemetry.should_skip(_args(), "install", environ={}, editable_probe=lambda: False) is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://user:pass@github.com/org/repo.git", "https://github.com/org/repo.git"),
        ("https://x-access-token:ghp_SECRET@github.com/org/repo", "https://github.com/org/repo"),
        ("git@github.com:org/repo.git", "github.com:org/repo.git"),
        ("ssh://git@host.example:22/org/repo", "ssh://host.example:22/org/repo"),
        ("https://github.com/org/repo.git", "https://github.com/org/repo.git"),
        ("https://user:pass@github.com/org/repo?token=x#frag", "https://github.com/org/repo"),
    ],
)
def test_strip_url_credentials(raw: str, expected: str) -> None:
    """Every URL shape has its userinfo (and query/fragment) removed, host+path kept."""
    assert telemetry.strip_url_credentials(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["", "   ", "not-a-url", "::::"])
def test_strip_url_credentials_unparseable_returns_none(raw: str) -> None:
    """An empty or unrecognised URL shape is dropped (None), never emitted verbatim."""
    assert telemetry.strip_url_credentials(raw) is None


@pytest.mark.unit
def test_split_repo_url_host_org_repo() -> None:
    """A credential-stripped URL splits into host, org (possibly nested), repo."""
    assert telemetry._split_repo_url("https://github.com/caylent/kanon.git") == ("github.com", "caylent", "kanon")
    assert telemetry._split_repo_url("https://gitlab.com/group/sub/proj") == ("gitlab.com", "group/sub", "proj")


@pytest.mark.unit
def test_collect_invocation_allowlist_only() -> None:
    """Only command/subcommand/boolean-flag-names and allowlisted values are collected."""
    args = _args(
        command="validate",
        validate_command="xml",
        refresh_lock=True,
        verbose=False,
        format="json",
        kanon_file="/home/secret-user/.kanon",
        target="https://x-access-token:ghp_SECRET@github.com/org/repo",
        catalog_source="https://tok:pw@example.com/manifest@main",
        lock_file="/tmp/SECRET.lock",
    )
    inv = telemetry.collect_invocation(args, "validate")

    assert inv["command"] == "validate"
    assert inv["subcommand"] == "xml"
    assert inv["flags"] == ["refresh_lock"]
    assert inv["flag_values"] == {"format": "json"}

    serialized = json.dumps(inv)
    for secret in ("ghp_SECRET", "secret-user", "SECRET.lock", "tok:pw", "/home/", "/tmp/"):
        assert secret not in serialized


@pytest.mark.unit
def test_collect_environment_shape() -> None:
    """The environment descriptor carries only non-sensitive runtime fields."""
    env = telemetry.collect_environment({constants.KANON_CI_ENV: "true"}, editable_probe=lambda: False)
    assert set(env) == {"kanon_version", "python_version", "os", "arch", "install_type", "is_ci"}
    assert env["python_version"] == platform.python_version()
    assert env["is_ci"] is True
    assert env["install_type"] in (
        constants.KANON_TELEMETRY_INSTALL_TYPE_WHEEL,
        constants.KANON_TELEMETRY_INSTALL_TYPE_EDITABLE,
        constants.KANON_TELEMETRY_INSTALL_TYPE_SOURCE,
    )


@pytest.mark.unit
def test_collect_git_metadata_credential_stripped() -> None:
    """Git provenance strips remote credentials and never emits the raw remote URL."""

    def _fake_git(git_args: list[str], *, cwd: Path, timeout: int) -> str | None:
        joined = " ".join(git_args)
        if joined == "config --get user.email":
            return "dev@example.com"
        if joined == "config --get remote.origin.url":
            return "https://x-access-token:ghp_SECRET@github.com/caylent/kanon.git"
        if joined == "rev-parse --abbrev-ref HEAD":
            return "feature/x"
        return None

    with patch.object(telemetry, "_run_git", side_effect=_fake_git):
        meta = telemetry.collect_git_metadata(Path("/repo"), timeout=3)

    assert meta["user_email"] == "dev@example.com"
    assert meta["remote_host"] == "github.com"
    assert meta["org"] == "caylent"
    assert meta["repo"] == "kanon"
    assert meta["branch"] == "feature/x"
    assert "ghp_SECRET" not in json.dumps(meta)


@pytest.mark.unit
def test_collect_git_metadata_non_git_dir_is_empty() -> None:
    """A directory that is not a git repo yields no git provenance keys."""
    with patch.object(telemetry, "_run_git", return_value=None):
        assert telemetry.collect_git_metadata(Path("/not-a-repo"), timeout=3) == {}


def _sample_lockfile() -> Lockfile:
    """Build a lockfile with one source, one resolved project, one url-less content pin."""
    return Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2026-07-14T00:00:00Z",
        generator="kanon-cli/3.2.0",
        kanon_hash="sha256:" + "a" * 64,
        sources=[
            SourceEntry(
                alias="FOO",
                name="foo",
                url="https://tok:pw@github.com/caylent/foo.git",
                ref_spec="main",
                resolved_ref="refs/heads/main",
                resolved_sha="a" * 40,
                path="repo-specs/foo.xml",
                includes=[
                    IncludeEntry(
                        name="inc",
                        path_in_repo="repo-specs/inc.xml",
                        url="https://github.com/caylent/foo",
                        resolved_sha="b" * 40,
                    )
                ],
                projects=[
                    ProjectEntry(
                        name="p1",
                        url="https://user:pw@github.com/caylent/p1.git",
                        canonical_url="https://github.com/caylent/p1",
                        ref_spec="*",
                        resolved_ref="main",
                        resolved_sha="c" * 40,
                    )
                ],
                content_pins=[
                    ContentPinEntry(name="p1", path="p1", resolved_sha="c" * 40),
                    ContentPinEntry(name="p2", path="p2", resolved_sha="d" * 40),
                ],
            )
        ],
    )


@pytest.mark.unit
def test_build_install_graph_direct_and_transitive() -> None:
    """The graph carries the direct source and every transitive package with URLs+shas."""
    graph, packages = telemetry.build_install_graph(_sample_lockfile())

    assert graph["lock_schema_version"] == CURRENT_SCHEMA_VERSION
    assert graph["sources"][0]["manifest_url"] == "https://github.com/caylent/foo.git"
    assert graph["sources"][0]["projects"][0]["url"] == "https://github.com/caylent/p1.git"
    assert graph["sources"][0]["include_chain"][0]["path_in_repo"] == "repo-specs/inc.xml"

    direct = [p for p in packages if p["scope"] == constants.KANON_TELEMETRY_SCOPE_DIRECT]
    transitive = [p for p in packages if p["scope"] == constants.KANON_TELEMETRY_SCOPE_TRANSITIVE]
    assert direct == [{"name": "foo", "url": "https://github.com/caylent/foo.git", "sha": "a" * 40, "scope": "direct"}]
    names = {p["name"]: p["url"] for p in transitive}
    assert names["p1"] == "https://github.com/caylent/p1.git"
    assert names["p2"] is None

    assert "tok:pw" not in json.dumps(graph)
    assert "user:pw" not in json.dumps(graph)


@pytest.mark.unit
def test_build_payload_install_includes_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An install command with a readable lockfile embeds the install graph + packages."""
    kanon_path = tmp_path / ".kanon"
    kanon_path.write_text("KANON_SOURCES=FOO\n", encoding="utf-8")
    write_lockfile(_sample_lockfile(), tmp_path / ".kanon.lock")

    args = _args(command="install", kanonenv_path=kanon_path, lock_file=None)
    payload = telemetry.build_payload(
        args,
        "install",
        exit_code=0,
        error_type=None,
        duration_ms=42,
        environ={},
        run_id="rid",
        cwd=tmp_path,
        editable_probe=lambda: False,
    )

    assert payload["outcome"] == {"exit_code": 0, "status": "ok", "error_type": None, "duration_ms": 42}
    assert "install_graph" in payload
    names = {p["name"] for p in payload["installed_packages"]}
    assert {"foo", "p1", "p2"} <= names


@pytest.mark.unit
def test_build_payload_non_install_has_no_graph(tmp_path: Path) -> None:
    """A non-install command carries no install graph or installed-packages list."""
    args = _args(command="search")
    payload = telemetry.build_payload(
        args,
        "search",
        exit_code=1,
        error_type="ValueError",
        duration_ms=7,
        environ={},
        run_id="rid",
        cwd=tmp_path,
        editable_probe=lambda: False,
    )
    assert "install_graph" not in payload
    assert "installed_packages" not in payload
    assert payload["outcome"]["status"] == "error"
    assert payload["outcome"]["error_type"] == "ValueError"


@pytest.mark.unit
def test_build_payload_graph_over_cap_is_truncated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An install graph over the size cap is dropped with a truncation flag; packages stay."""
    kanon_path = tmp_path / ".kanon"
    kanon_path.write_text("KANON_SOURCES=FOO\n", encoding="utf-8")
    write_lockfile(_sample_lockfile(), tmp_path / ".kanon.lock")
    monkeypatch.setattr(constants, "KANON_TELEMETRY_GRAPH_SIZE_CAP", 1, raising=False)

    args = _args(command="install", kanonenv_path=kanon_path, lock_file=None)
    payload = telemetry.build_payload(
        args,
        "install",
        exit_code=0,
        error_type=None,
        duration_ms=1,
        environ={},
        run_id="rid",
        cwd=tmp_path,
        editable_probe=lambda: False,
    )
    assert payload.get("install_graph_truncated") is True
    assert "install_graph" not in payload
    assert "installed_packages" in payload


@pytest.mark.unit
def test_serialize_body_has_four_top_level_keys_and_string_payload() -> None:
    """The collector body has exactly tool/timestamp/event_type/payload; payload is a JSON string."""
    body_str = telemetry._serialize_body({"schema_version": 1}, "2026-07-14T00:00:00Z")
    body = json.loads(body_str)
    assert set(body) == {"tool", "timestamp", "event_type", "payload"}
    assert body["tool"] == constants.KANON_TELEMETRY_TOOL_NAME
    assert body["event_type"] == constants.KANON_TELEMETRY_EVENT_TYPE
    assert isinstance(body["payload"], str)
    assert json.loads(body["payload"]) == {"schema_version": 1}


@pytest.mark.unit
def test_build_otlp_request_body_is_verbatim() -> None:
    """The OTLP log record body.stringValue is the flat collector body verbatim."""
    otlp = telemetry.build_otlp_request("BODY", timestamp_ns=123, resource_version="3.3.0")
    record = otlp["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    assert record["body"]["stringValue"] == "BODY"
    assert record["timeUnixNano"] == "123"


@pytest.mark.unit
def test_cap_body_final_guard_drops_heavy_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the serialized body exceeds the body cap the graph+packages are dropped."""
    monkeypatch.setattr(constants, "KANON_TELEMETRY_MAX_BODY_BYTES", 200, raising=False)
    payload = {
        "schema_version": 1,
        "install_graph": {"x": "y"},
        "installed_packages": [{"name": f"pkg{i}"} for i in range(50)],
    }
    body_str = telemetry._cap_body(payload, "2026-07-14T00:00:00Z")
    assert payload.get("install_graph_truncated") is True
    assert "install_graph" not in payload
    assert payload["installed_packages_count"] == 50
    assert len(body_str.encode("utf-8")) <= 200 or "installed_packages_count" in body_str


@pytest.mark.unit
def test_post_telemetry_posts_json_with_headers() -> None:
    """post_telemetry issues an HTTPS POST with the OTLP bytes, Content-Type, and User-Agent."""
    captured: dict[str, object] = {}

    def _fake_urlopen(request: object, timeout: int | None = None) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["data"] = request.data
        captured["content_type"] = request.get_header("Content-type")
        captured["user_agent"] = request.get_header("User-agent")
        captured["timeout"] = timeout
        return _FakeResponse()

    with patch.object(telemetry.urllib.request, "urlopen", side_effect=_fake_urlopen):
        telemetry.post_telemetry(
            b'{"a":1}',
            endpoint="https://collector.example/v1/logs",
            connect_timeout=2,
            read_timeout=3,
            user_agent="kanon-cli/9.9.9",
        )

    assert captured["method"] == "POST"
    assert captured["data"] == b'{"a":1}'
    assert captured["content_type"] == constants.KANON_TELEMETRY_CONTENT_TYPE
    assert captured["user_agent"] == "kanon-cli/9.9.9"
    assert captured["timeout"] == 3


@pytest.mark.unit
def test_post_telemetry_rejects_non_https() -> None:
    """A non-HTTPS endpoint is refused before any network call."""
    with patch.object(telemetry.urllib.request, "urlopen") as urlopen:
        with pytest.raises(ValueError):
            telemetry.post_telemetry(
                b"{}",
                endpoint="http://collector.example/v1/logs",
                connect_timeout=2,
                read_timeout=3,
                user_agent="kanon-cli/9.9.9",
            )
    urlopen.assert_not_called()


@pytest.mark.unit
def test_resolve_endpoint_precedence() -> None:
    """Endpoint precedence is flag > env > default."""
    assert telemetry.resolve_endpoint(_args(telemetry_endpoint="https://flag/v1/logs"), {}) == "https://flag/v1/logs"
    assert (
        telemetry.resolve_endpoint(_args(), {constants.KANON_TELEMETRY_ENDPOINT_ENV: "https://env/v1/logs"})
        == "https://env/v1/logs"
    )
    assert telemetry.resolve_endpoint(_args(), {}) == constants.KANON_TELEMETRY_ENDPOINT_DEFAULT


@pytest.mark.unit
def test_is_debug_flag_or_env() -> None:
    """Debug mode is enabled by the flag or the env var."""
    assert telemetry.is_debug(_args(telemetry_debug=True), {}) is True
    assert telemetry.is_debug(_args(), {constants.KANON_TELEMETRY_DEBUG_ENV: "1"}) is True
    assert telemetry.is_debug(_args(), {}) is False


@pytest.mark.unit
def test_maybe_emit_skipped_disabled_no_spawn_no_output() -> None:
    """When disabled the emitter spawns nothing and prints nothing."""
    calls, spawn = _inline_spawn_capture()
    stream = io.StringIO()
    telemetry.maybe_emit_telemetry(
        _args(command="install"),
        "install",
        exit_code=0,
        error_type=None,
        duration_ms=1,
        environ={constants.KANON_TELEMETRY_DISABLED_ENV: "1"},
        stream=stream,
        spawn=spawn,
    )
    assert calls == []
    assert stream.getvalue() == ""


@pytest.mark.unit
def test_maybe_emit_happy_path_posts_once(tmp_path: Path) -> None:
    """The happy path builds the event and fires exactly one detached POST."""
    calls, spawn = _inline_spawn_capture()
    captured: dict[str, object] = {}

    def _fake_urlopen(request: object, timeout: int | None = None) -> _FakeResponse:
        captured["data"] = request.data
        captured["url"] = request.full_url
        return _FakeResponse()

    with (
        patch.object(telemetry, "is_editable_install", return_value=True),
        patch.object(telemetry.urllib.request, "urlopen", side_effect=_fake_urlopen),
    ):
        telemetry.maybe_emit_telemetry(
            _args(command="why"),
            "why",
            exit_code=0,
            error_type=None,
            duration_ms=3,
            environ={
                constants.KANON_TELEMETRY_FORCE_ENV: "1",
                constants.KANON_TELEMETRY_ENDPOINT_ENV: "https://collector.example/v1/logs",
            },
            cwd=tmp_path,
            spawn=spawn,
        )

    assert len(calls) == 1
    assert captured["url"] == "https://collector.example/v1/logs"
    body = json.loads(captured["data"].decode("utf-8"))
    record_body = body["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"]["stringValue"]
    assert json.loads(record_body)["tool"] == "kanon"


@pytest.mark.unit
def test_maybe_emit_debug_prints_json_and_still_spawns(tmp_path: Path) -> None:
    """Debug mode prints the exact OTLP JSON to the stream and still spawns the POST."""
    calls, spawn = _inline_spawn_capture()
    stream = io.StringIO()
    with (
        patch.object(telemetry, "is_editable_install", return_value=True),
        patch.object(telemetry.urllib.request, "urlopen", return_value=_FakeResponse()),
    ):
        telemetry.maybe_emit_telemetry(
            _args(command="why", telemetry_debug=True),
            "why",
            exit_code=0,
            error_type=None,
            duration_ms=3,
            environ={
                constants.KANON_TELEMETRY_FORCE_ENV: "1",
                constants.KANON_TELEMETRY_ENDPOINT_ENV: "https://collector.example/v1/logs",
            },
            cwd=tmp_path,
            stream=stream,
            spawn=spawn,
        )
    printed = stream.getvalue()
    assert "resourceLogs" in printed
    assert json.loads(printed)
    assert len(calls) == 1


@pytest.mark.unit
def test_maybe_emit_never_raises_on_build_error(tmp_path: Path) -> None:
    """A payload-build failure is swallowed (never raised) and no spawn occurs."""
    calls, spawn = _inline_spawn_capture()
    with (
        patch.object(telemetry, "is_editable_install", return_value=False),
        patch.object(telemetry, "build_payload", side_effect=RuntimeError("boom")),
    ):
        telemetry.maybe_emit_telemetry(
            _args(command="why"),
            "why",
            exit_code=0,
            error_type=None,
            duration_ms=1,
            environ={},
            cwd=tmp_path,
            spawn=spawn,
        )
    assert calls == []


def _record_only_spawn() -> tuple[list[Path], Any]:
    """Return (log_paths, spawn_fn) where spawn_fn records the call without POSTing."""
    log_paths: list[Path] = []

    def _spawn(fn: Any, *, log_path: Path) -> None:
        log_paths.append(log_path)

    return log_paths, _spawn


def _payload_from_debug_stream(stream: io.StringIO) -> dict[str, Any]:
    """Parse the debug OTLP JSON printed to the stream and return the inner payload dict."""
    otlp = json.loads(stream.getvalue())
    body_str = otlp["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"]["stringValue"]
    return json.loads(json.loads(body_str)["payload"])


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv,expected",
    [
        (["--version"], "--version"),
        (["--version", "--telemetry-debug"], "--version"),
        (["--help"], "--help"),
        (["-h"], "--help"),
        (["install", "--help"], "--help"),
        (["--help", "--version"], "--help"),
        (["--version", "--help"], "--version"),
        ([], "<none>"),
        (["--telemetry-debug"], "<none>"),
    ],
)
def test_early_exit_command_derivation(argv: list[str], expected: str) -> None:
    """The early-exit command label is the first version/help token, else the bare sentinel."""
    assert telemetry.early_exit_command(argv) == expected


@pytest.mark.unit
def test_build_early_exit_args_recovers_debug_and_endpoint_space_form() -> None:
    """The recovered namespace carries the debug flag and the space-form endpoint value."""
    args = telemetry.build_early_exit_args(
        ["--version", "--telemetry-debug", "--telemetry-endpoint", "https://sandbox/v1/logs"],
        "--version",
    )
    assert args.command == "--version"
    assert args.telemetry_debug is True
    assert args.telemetry_endpoint == "https://sandbox/v1/logs"


@pytest.mark.unit
def test_build_early_exit_args_recovers_equals_form_endpoint() -> None:
    """The ``--telemetry-endpoint=<url>`` joined form is recovered and debug stays unset."""
    args = telemetry.build_early_exit_args(["--telemetry-endpoint=https://x/v1/logs"], "<none>")
    assert args.telemetry_endpoint == "https://x/v1/logs"
    assert not hasattr(args, "telemetry_debug")


@pytest.mark.unit
def test_build_early_exit_args_bare_has_no_recovered_flags() -> None:
    """A bare argv yields a namespace with only the command and no recovered telemetry flags."""
    args = telemetry.build_early_exit_args([], "<none>")
    assert args.command == "<none>"
    assert not hasattr(args, "telemetry_debug")
    assert not hasattr(args, "telemetry_endpoint")


@pytest.mark.unit
def test_maybe_emit_early_exit_version_records_ok(tmp_path: Path) -> None:
    """A --version early exit emits command '--version' with a zero exit code and ok status."""
    log_paths, spawn = _record_only_spawn()
    stream = io.StringIO()
    with patch.object(telemetry, "is_editable_install", return_value=False):
        telemetry.maybe_emit_early_exit_telemetry(
            ["--version", "--telemetry-debug"],
            0,
            environ={},
            cwd=tmp_path,
            stream=stream,
            spawn=spawn,
        )

    payload = _payload_from_debug_stream(stream)
    assert payload["invocation"]["command"] == "--version"
    assert payload["outcome"]["exit_code"] == 0
    assert payload["outcome"]["status"] == constants.KANON_TELEMETRY_STATUS_OK
    assert payload["outcome"]["error_type"] is None
    assert len(log_paths) == 1


@pytest.mark.unit
def test_maybe_emit_early_exit_bare_records_error(tmp_path: Path) -> None:
    """A bare invocation (exit 2) emits the '<none>' sentinel with an error status + SystemExit type."""
    log_paths, spawn = _record_only_spawn()
    stream = io.StringIO()
    with patch.object(telemetry, "is_editable_install", return_value=False):
        telemetry.maybe_emit_early_exit_telemetry(
            ["--telemetry-debug"],
            2,
            environ={},
            cwd=tmp_path,
            stream=stream,
            spawn=spawn,
        )

    payload = _payload_from_debug_stream(stream)
    assert payload["invocation"]["command"] == constants.KANON_TELEMETRY_EARLY_EXIT_COMMAND
    assert payload["outcome"]["exit_code"] == 2
    assert payload["outcome"]["status"] == constants.KANON_TELEMETRY_STATUS_ERROR
    assert payload["outcome"]["error_type"] == "SystemExit"
    assert len(log_paths) == 1


@pytest.mark.unit
def test_maybe_emit_early_exit_disabled_env_skips(tmp_path: Path) -> None:
    """The opt-out env var suppresses the early-exit event even with the debug flag present."""
    log_paths, spawn = _record_only_spawn()
    stream = io.StringIO()
    telemetry.maybe_emit_early_exit_telemetry(
        ["--version", "--telemetry-debug"],
        0,
        environ={constants.KANON_TELEMETRY_DISABLED_ENV: "1"},
        cwd=tmp_path,
        stream=stream,
        spawn=spawn,
    )
    assert log_paths == []
    assert stream.getvalue() == ""


@pytest.mark.unit
def test_maybe_emit_early_exit_help_emits_via_short_flag(tmp_path: Path) -> None:
    """The -h alias emits the '--help' command label, proving the alias reaches telemetry."""
    log_paths, spawn = _record_only_spawn()
    stream = io.StringIO()
    with patch.object(telemetry, "is_editable_install", return_value=False):
        telemetry.maybe_emit_early_exit_telemetry(
            ["-h", "--telemetry-debug"],
            0,
            environ={},
            cwd=tmp_path,
            stream=stream,
            spawn=spawn,
        )
    payload = _payload_from_debug_stream(stream)
    assert payload["invocation"]["command"] == "--help"
    assert len(log_paths) == 1


@pytest.mark.unit
def test_no_secret_scan_over_command_matrix(tmp_path: Path) -> None:
    """No planted credential ever appears in any serialized event body across a command matrix."""
    secrets = ["ghp_TOPSECRET", "AKIAEXAMPLESECRET", "s3cr3t-passphrase"]
    remote_with_secret = f"https://x-access-token:{secrets[0]}@github.com/org/repo.git"

    def _fake_git(git_args: list[str], *, cwd: Path, timeout: int) -> str | None:
        joined = " ".join(git_args)
        if joined == "config --get user.email":
            return "dev@example.com"
        if joined == "config --get remote.origin.url":
            return remote_with_secret
        if joined == "rev-parse --abbrev-ref HEAD":
            return "main"
        return None

    matrix = [
        _args(command="install", kanonenv_path=tmp_path / f"/{secrets[1]}/.kanon", lock_file=None),
        _args(command="why", target=remote_with_secret),
        _args(command="add", catalog_source=f"https://u:{secrets[2]}@example.com/m@main", names=[secrets[0]]),
        _args(command="search", query=secrets[2], format="json"),
    ]

    with patch.object(telemetry, "_run_git", side_effect=_fake_git):
        for args in matrix:
            payload = telemetry.build_payload(
                args,
                args.command,
                exit_code=0,
                error_type=None,
                duration_ms=1,
                environ={},
                run_id="rid",
                cwd=tmp_path,
                editable_probe=lambda: False,
            )
            body_str = telemetry._cap_body(payload, "2026-07-14T00:00:00Z")
            for secret in secrets:
                assert secret not in body_str, f"secret {secret!r} leaked in {args.command} body"


_SECRET_TOKEN = "ghp_FAKE0000000000000000000000000000000000"
_SECRET_URL_PW = "SUPERSECRET"
_SECRET_FLAG_PW = "FLAGSECRET"
_SECRET_GIT_USER = "baduser"


def _no_op_git(git_args: list[str], *, cwd: Path, timeout: int) -> str | None:
    """A git seam that reports no provenance (a non-git working directory)."""
    return None


def _serialize_emitted_otlp(
    args: argparse.Namespace,
    command: str,
    cwd: Path,
    *,
    git: Any = _no_op_git,
) -> str:
    """Serialize the full OTLP request exactly as the emitter would, for secret scanning."""
    with patch.object(telemetry, "_run_git", side_effect=git):
        payload = telemetry.build_payload(
            args,
            command,
            exit_code=0,
            error_type=None,
            duration_ms=1,
            environ={},
            run_id="rid",
            cwd=cwd,
            editable_probe=lambda: False,
        )
    body_str = telemetry._cap_body(payload, "2026-07-14T00:00:00Z")
    otlp = telemetry.build_otlp_request(body_str, timestamp_ns=1, resource_version="9.9.9")
    return json.dumps(otlp, separators=(",", ":"), sort_keys=True)


def _cred_remote_git(git_args: list[str], *, cwd: Path, timeout: int) -> str | None:
    """A git seam whose origin URL and committer carry credential-shaped secrets."""
    joined = " ".join(git_args)
    if joined == "config --get user.email":
        return "dev@example.com"
    if joined == "config --get remote.origin.url":
        return f"https://{_SECRET_GIT_USER}:PW@github.com/secretorg/secretrepo.git"
    if joined == "rev-parse --abbrev-ref HEAD":
        return "main"
    return None


@pytest.mark.unit
@pytest.mark.parametrize(
    "args_factory",
    [
        lambda: _args(
            command="add",
            names=[_SECRET_TOKEN],
            catalog_source=f"https://user:{_SECRET_URL_PW}@github.com/secretorg/secretrepo@main",
            telemetry_endpoint=f"https://tok:{_SECRET_FLAG_PW}@host/v1/logs",
        ),
        lambda: _args(
            command="why",
            target=f"https://user:{_SECRET_URL_PW}@github.com/secretorg/secretrepo",
            telemetry_endpoint=f"https://tok:{_SECRET_FLAG_PW}@host/v1/logs",
        ),
        lambda: _args(command="install", kanonenv_path=f"/{_SECRET_TOKEN}/.kanon", lock_file=None),
    ],
    ids=["add-token-and-cred-source", "why-cred-target", "install-secret-path"],
)
def test_zero_secret_no_leak_in_serialized_otlp(args_factory: Any, tmp_path: Path) -> None:
    """No secret-shaped input (token, URL password, endpoint password, git userinfo) survives serialization.

    Security-critical guard (T8): builds the full OTLP request the emitter would
    POST -- for a fake token positional, a credentialed source URL, a credentialed
    ``--telemetry-endpoint``, and a credentialed git remote -- and asserts none of
    those secret substrings appear anywhere in the serialized bytes. It fails
    loudly if the allowlist is ever widened to serialize a free-form value.
    """
    args = args_factory()
    serialized = _serialize_emitted_otlp(args, args.command, tmp_path, git=_cred_remote_git)
    for secret in (_SECRET_TOKEN, _SECRET_URL_PW, _SECRET_FLAG_PW, _SECRET_GIT_USER, "user:", "tok:", ":PW@"):
        assert secret not in serialized, f"secret {secret!r} leaked in {args.command} OTLP body"


@pytest.mark.unit
def test_serialized_otlp_credential_stripped_git_to_host_org_repo(tmp_path: Path) -> None:
    """A credentialed git remote is reduced to host+org+repo only inside the serialized OTLP (T8)."""
    args = _args(command="doctor")
    serialized = _serialize_emitted_otlp(args, "doctor", tmp_path, git=_cred_remote_git)
    payload = json.loads(
        json.loads(serialized)["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"]["stringValue"]
    )
    git = json.loads(payload["payload"])["git"]
    assert git["remote_host"] == "github.com"
    assert git["org"] == "secretorg"
    assert git["repo"] == "secretrepo"
    assert _SECRET_GIT_USER not in serialized


@pytest.mark.unit
def test_invocation_serializes_only_allowlist_no_raw_argv() -> None:
    """The invocation carries exactly the allowlist keys; no positional/path/URL value leaks (T8)."""
    args = _args(
        command="add",
        names=[_SECRET_TOKEN],
        catalog_source=f"https://u:{_SECRET_URL_PW}@example.com/m@main",
        kanon_file="/home/secret-user/.kanon",
        format="json",
        refresh_lock=True,
    )
    inv = telemetry.collect_invocation(args, "add")
    assert set(inv) == {"command", "subcommand", "flags", "flag_values"}
    assert inv["flag_values"] == {"format": "json"}
    assert "refresh_lock" in inv["flags"]
    serialized = json.dumps(inv)
    for secret in (_SECRET_TOKEN, _SECRET_URL_PW, "secret-user", "/home/"):
        assert secret not in serialized


def _registered_top_level_commands() -> list[str]:
    """Return every top-level command name registered on the real kanon parser."""
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return list(action.choices.keys())
    return []


@pytest.mark.unit
def test_every_real_subcommand_emits_and_completers_skip() -> None:
    """Every real subcommand is emit-eligible while every ``__complete*`` completer is skipped (T1).

    Derives the command set from the live parser so a newly registered subcommand
    is covered automatically: a real command on a wheel install must NOT skip
    (it would emit) and every completer subcommand MUST skip.
    """
    commands = _registered_top_level_commands()
    real = [c for c in commands if not c.startswith(constants.KANON_COMPLETER_COMMAND_PREFIX)]
    completers = [c for c in commands if c.startswith(constants.KANON_COMPLETER_COMMAND_PREFIX)]
    assert real, "expected at least one real subcommand registered"
    assert completers, "expected at least one completer subcommand registered"

    for command in real:
        assert (
            telemetry.should_skip(_args(command=command), command, environ={}, editable_probe=lambda: False) is False
        ), f"real command {command!r} must be emit-eligible"
    for command in completers:
        assert (
            telemetry.should_skip(_args(command=command), command, environ={}, editable_probe=lambda: False) is True
        ), f"completer {command!r} must be skipped"


@pytest.mark.unit
def test_maybe_emit_default_dispatch_uses_detached_spawn(tmp_path: Path) -> None:
    """With no injected seam the emitter dispatches the POST via the detached spawn_detached (T6, non-blocking)."""
    with (
        patch.object(telemetry, "is_editable_install", return_value=False),
        patch.object(telemetry, "spawn_detached") as detached,
    ):
        telemetry.maybe_emit_telemetry(
            _args(command="why"),
            "why",
            exit_code=0,
            error_type=None,
            duration_ms=1,
            environ={constants.KANON_TELEMETRY_ENDPOINT_ENV: "https://collector.example/v1/logs"},
            cwd=tmp_path,
        )
    detached.assert_called_once()


@pytest.mark.unit
def test_maybe_emit_foreground_does_not_perform_the_post(tmp_path: Path) -> None:
    """The foreground hands the POST to the spawn seam and never calls urlopen itself (T6, non-blocking)."""
    log_paths, spawn = _record_only_spawn()
    with (
        patch.object(telemetry, "is_editable_install", return_value=False),
        patch.object(telemetry.urllib.request, "urlopen") as urlopen,
    ):
        telemetry.maybe_emit_telemetry(
            _args(command="why"),
            "why",
            exit_code=0,
            error_type=None,
            duration_ms=1,
            environ={constants.KANON_TELEMETRY_ENDPOINT_ENV: "https://collector.example/v1/logs"},
            cwd=tmp_path,
            spawn=spawn,
        )
    urlopen.assert_not_called()
    assert len(log_paths) == 1


@pytest.mark.unit
def test_maybe_emit_never_raises_when_post_fails(tmp_path: Path) -> None:
    """A transport failure raised inside the dispatched POST is swallowed; emit never raises (T6, never-fail)."""
    calls, spawn = _inline_spawn_capture()
    with (
        patch.object(telemetry, "is_editable_install", return_value=False),
        patch.object(telemetry.urllib.request, "urlopen", side_effect=OSError("network unreachable")),
    ):
        telemetry.maybe_emit_telemetry(
            _args(command="why"),
            "why",
            exit_code=0,
            error_type=None,
            duration_ms=1,
            environ={constants.KANON_TELEMETRY_ENDPOINT_ENV: "https://collector.example/v1/logs"},
            cwd=tmp_path,
            spawn=spawn,
        )
    assert len(calls) == 1


@pytest.mark.unit
def test_maybe_emit_debug_writes_nothing_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Debug telemetry goes to the debug stream only; stdout stays clean so a --format json document stays valid (T5)."""
    _log_paths, spawn = _record_only_spawn()
    stream = io.StringIO()
    with patch.object(telemetry, "is_editable_install", return_value=False):
        telemetry.maybe_emit_telemetry(
            _args(command="search", format="json", telemetry_debug=True),
            "search",
            exit_code=0,
            error_type=None,
            duration_ms=1,
            environ={},
            cwd=tmp_path,
            stream=stream,
            spawn=spawn,
        )
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = _payload_from_debug_stream(stream)
    assert payload["invocation"]["flag_values"] == {"format": "json"}


@pytest.mark.unit
def test_install_type_classifies_source_editable_and_wheel() -> None:
    """_install_type maps a missing distribution to source, an editable dist to editable, else wheel (T9)."""
    with patch.object(telemetry.metadata, "distribution", side_effect=telemetry.metadata.PackageNotFoundError):
        assert telemetry._install_type(lambda: True) == constants.KANON_TELEMETRY_INSTALL_TYPE_SOURCE

    with patch.object(telemetry.metadata, "distribution", return_value=object()):
        assert telemetry._install_type(lambda: True) == constants.KANON_TELEMETRY_INSTALL_TYPE_EDITABLE
        assert telemetry._install_type(lambda: False) == constants.KANON_TELEMETRY_INSTALL_TYPE_WHEEL


@pytest.mark.unit
@pytest.mark.parametrize(
    "environ,expected",
    [
        ({constants.KANON_CI_ENV: "true"}, True),
        ({constants.KANON_CI_ENV: "1"}, True),
        ({constants.KANON_CI_ENV: "false"}, False),
        ({}, False),
    ],
)
def test_collect_environment_is_ci_detection(environ: dict[str, str], expected: bool) -> None:
    """is_ci is True only for a truthy CI env var and False when unset or falsey (T10)."""
    env = telemetry.collect_environment(environ, editable_probe=lambda: False)
    assert env["is_ci"] is expected


@pytest.mark.unit
def test_install_graph_exposes_transitive_project_layer(tmp_path: Path) -> None:
    """The install graph and installed_packages expose the transitive project layer of the lockfile (W1)."""
    kanon_path = tmp_path / ".kanon"
    kanon_path.write_text("KANON_SOURCES=FOO\n", encoding="utf-8")
    write_lockfile(_sample_lockfile(), tmp_path / ".kanon.lock")

    args = _args(command="install", kanonenv_path=kanon_path, lock_file=None)
    payload = telemetry.build_payload(
        args,
        "install",
        exit_code=0,
        error_type=None,
        duration_ms=1,
        environ={},
        run_id="rid",
        cwd=tmp_path,
        editable_probe=lambda: False,
    )
    transitive = [p for p in payload["installed_packages"] if p["scope"] == constants.KANON_TELEMETRY_SCOPE_TRANSITIVE]
    transitive_names = {p["name"] for p in transitive}
    assert {"p1", "p2"} <= transitive_names
    graph_projects = payload["install_graph"]["sources"][0]["projects"]
    assert any(project["scope"] == constants.KANON_TELEMETRY_SCOPE_TRANSITIVE for project in graph_projects)
    assert graph_projects[0]["name"] == "p1"
