"""Unit tests for kanon_cli.core.update_check (spec Section 7.1 / FR-29).

Covers the PyPI update-available alert end to end at the unit level:

- the lookup hardening (timeouts, body-size cap, User-Agent, HTTPS-only,
  graceful-fail on any network/parse error);
- the TTL cache (FRESH reuse, STALE serve-then-background-refresh, MISSING inline
  fetch), reusing the completions/cache.py primitives under a tmp KANON_HOME;
- every skip condition (completer subcommand, KANON_SKIP_UPDATE_CHECK=1,
  --no-update-check, dev/editable install) short-circuiting before any network or
  cache access;
- the alert being printed to stderr (the injected stream) only when a strictly
  newer version is available, silent when current, and graceful-fail (no alert,
  no error) when the lookup fails / times out / is oversized;
- the constants knobs (TTL / connect / read / size-cap) being read from
  constants.py via _env_int.

Every test injects the network seam, the editable-install probe, the "now" clock,
the environment mapping, and the output stream, so no test touches the live PyPI
endpoint or the operator's real ~/.kanon-home store. All assertions are real and can
fail if the code is wrong.
"""

from __future__ import annotations

import argparse
import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

import kanon_cli.constants as constants
from kanon_cli.completions.cache import Freshness
from kanon_cli.core import update_check


def _args(**overrides: object) -> argparse.Namespace:
    """Build an argparse namespace with a default no_update_check=False."""
    ns = argparse.Namespace(no_update_check=False)
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


@pytest.fixture(autouse=True)
def _isolated_kanon_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point KANON_HOME at a tmp dir so the cache never touches the real store."""
    home = tmp_path / "kanon-home"
    monkeypatch.setenv(constants.KANON_HOME_ENV_VAR, str(home))

    monkeypatch.setattr(constants, "_NO_COLOR_ACTIVE", False, raising=False)
    return home


@pytest.mark.unit
@pytest.mark.parametrize(
    "command",
    [
        "__complete_catalog_entries",
        "__complete_catalog_versions",
        "__complete_names_in_lockfile",
        "__complete_source_names_in_kanon",
        "__complete_project_versions",
        "__complete_cached_catalogs",
    ],
)
def test_should_skip_completer_subcommands(command: str) -> None:
    """Every registered __complete_* completer invocation is skipped."""
    skipped = update_check.should_skip(
        _args(),
        command,
        environ={},
        editable_probe=lambda: False,
    )
    assert skipped is True


@pytest.mark.unit
def test_should_skip_env_flag_set_to_one() -> None:
    """KANON_SKIP_UPDATE_CHECK=1 skips the check."""
    assert (
        update_check.should_skip(
            _args(),
            "install",
            environ={constants.KANON_SKIP_UPDATE_CHECK_ENV: "1"},
            editable_probe=lambda: False,
        )
        is True
    )


@pytest.mark.unit
def test_should_not_skip_env_flag_other_value() -> None:
    """A non-'1' value of KANON_SKIP_UPDATE_CHECK does not skip."""
    assert (
        update_check.should_skip(
            _args(),
            "install",
            environ={constants.KANON_SKIP_UPDATE_CHECK_ENV: "0"},
            editable_probe=lambda: False,
        )
        is False
    )


@pytest.mark.unit
def test_should_skip_no_update_check_flag() -> None:
    """The --no-update-check global flag skips the check."""
    assert (
        update_check.should_skip(
            _args(no_update_check=True),
            "install",
            environ={},
            editable_probe=lambda: False,
        )
        is True
    )


@pytest.mark.unit
def test_should_skip_editable_install() -> None:
    """A dev/editable install skips the check."""
    assert (
        update_check.should_skip(
            _args(),
            "install",
            environ={},
            editable_probe=lambda: True,
        )
        is True
    )


@pytest.mark.unit
def test_should_not_skip_normal_install() -> None:
    """A normal command on a wheel install does not skip."""
    assert (
        update_check.should_skip(
            _args(),
            "install",
            environ={},
            editable_probe=lambda: False,
        )
        is False
    )


@pytest.mark.unit
def test_maybe_alert_skip_makes_no_network_or_cache_call() -> None:
    """When skipped, no fetch, no cache read, and no write occur, and stderr stays empty."""
    stream = io.StringIO()
    with (
        patch.object(update_check, "fetch_latest_version") as fetch,
        patch.object(update_check, "read_cached_version") as read_cache,
        patch.object(update_check, "write_cached_version") as write_cache,
        patch.object(update_check, "is_editable_install", return_value=True),
    ):
        update_check.maybe_alert_update(_args(), "install", environ={}, stream=stream, now=1000)
    fetch.assert_not_called()
    read_cache.assert_not_called()
    write_cache.assert_not_called()
    assert stream.getvalue() == ""


@pytest.mark.unit
def test_is_editable_install_true_when_distribution_missing() -> None:
    """A running-from-source checkout (no distribution) is treated as editable."""
    from importlib import metadata

    with patch.object(update_check.metadata, "distribution", side_effect=metadata.PackageNotFoundError()):
        assert update_check.is_editable_install() is True


@pytest.mark.unit
def test_is_editable_install_true_when_direct_url_editable() -> None:
    """direct_url.json with dir_info.editable=true marks an editable install."""

    class _Dist:
        def read_text(self, name: str) -> str | None:
            assert name == "direct_url.json"
            return json.dumps({"url": "file:///somewhere", "dir_info": {"editable": True}})

    with patch.object(update_check.metadata, "distribution", return_value=_Dist()):
        assert update_check.is_editable_install() is True


@pytest.mark.unit
def test_is_editable_install_false_for_wheel_install() -> None:
    """A wheel install (no direct_url.json) is not editable."""

    class _Dist:
        def read_text(self, name: str) -> str | None:
            return None

    with patch.object(update_check.metadata, "distribution", return_value=_Dist()):
        assert update_check.is_editable_install() is False


@pytest.mark.unit
def test_is_editable_install_false_when_direct_url_not_editable() -> None:
    """direct_url.json with dir_info.editable=false is not editable."""

    class _Dist:
        def read_text(self, name: str) -> str | None:
            return json.dumps({"url": "https://files.pythonhosted.org/x.whl"})

    with patch.object(update_check.metadata, "distribution", return_value=_Dist()):
        assert update_check.is_editable_install() is False


class _FakeResponse:
    """Minimal context-manager stand-in for urllib's response object."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, amt: int) -> bytes:
        return self._body[:amt]


@pytest.mark.unit
def test_fetch_latest_version_success_parses_info_version() -> None:
    """A well-formed PyPI payload yields info.version."""
    payload = json.dumps({"info": {"version": "9.9.9"}}).encode("utf-8")
    with patch.object(update_check.urllib.request, "urlopen", return_value=_FakeResponse(payload)):
        assert update_check.fetch_latest_version() == "9.9.9"


@pytest.mark.unit
def test_fetch_latest_version_sets_user_agent_and_timeout() -> None:
    """The request carries an explicit User-Agent; urlopen gets the env-driven timeout."""
    payload = json.dumps({"info": {"version": "9.9.9"}}).encode("utf-8")
    captured: dict[str, object] = {}

    def _fake_urlopen(request: object, timeout: int | None = None) -> _FakeResponse:
        captured["user_agent"] = request.get_header("User-agent")
        captured["timeout"] = timeout
        return _FakeResponse(payload)

    with patch.object(update_check.urllib.request, "urlopen", side_effect=_fake_urlopen):
        update_check.fetch_latest_version(connect_timeout=2, read_timeout=3)

    assert captured["user_agent"] is not None
    assert constants.KANON_PYPI_PROJECT_NAME in str(captured["user_agent"])

    assert captured["timeout"] == 3


@pytest.mark.unit
def test_fetch_latest_version_rejects_non_https_url() -> None:
    """A non-HTTPS URL is refused without any network call (returns None)."""
    with patch.object(update_check.urllib.request, "urlopen") as urlopen:
        result = update_check.fetch_latest_version(url="http://pypi.example/insecure")
    assert result is None
    urlopen.assert_not_called()


@pytest.mark.unit
def test_fetch_latest_version_oversized_body_returns_none() -> None:
    """A response body exceeding the cap is abandoned (no version)."""
    cap = 16

    oversized = b"x" * (cap + 1)
    with patch.object(update_check.urllib.request, "urlopen", return_value=_FakeResponse(oversized)):
        assert update_check.fetch_latest_version(body_size_cap=cap) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "raised",
    [
        urllib.error.URLError("timed out"),
        urllib.error.HTTPError("https://pypi.org", 503, "busy", {}, None),
        OSError("connection reset"),
    ],
)
def test_fetch_latest_version_network_error_returns_none(raised: Exception) -> None:
    """Any network error yields None (graceful-fail, never raised)."""
    with patch.object(update_check.urllib.request, "urlopen", side_effect=raised):
        assert update_check.fetch_latest_version() is None


@pytest.mark.unit
def test_fetch_latest_version_malformed_json_returns_none() -> None:
    """A non-JSON body yields None."""
    with patch.object(update_check.urllib.request, "urlopen", return_value=_FakeResponse(b"not json")):
        assert update_check.fetch_latest_version() is None


@pytest.mark.unit
def test_fetch_latest_version_missing_info_returns_none() -> None:
    """A payload without info.version yields None."""
    payload = json.dumps({"info": {}}).encode("utf-8")
    with patch.object(update_check.urllib.request, "urlopen", return_value=_FakeResponse(payload)):
        assert update_check.fetch_latest_version() is None


@pytest.mark.unit
def test_cache_round_trip_fresh() -> None:
    """A freshly written version reads back FRESH within the TTL."""
    update_check.write_cached_version("3.2.1", now=1000)
    version, freshness = update_check.read_cached_version(now=1000 + 10, ttl_seconds=86400)
    assert version == "3.2.1"
    assert freshness is Freshness.FRESH


@pytest.mark.unit
def test_cache_read_stale_past_ttl() -> None:
    """A version older than the TTL reads back STALE but still returns the value."""
    update_check.write_cached_version("3.2.1", now=1000)
    version, freshness = update_check.read_cached_version(now=1000 + 100000, ttl_seconds=86400)
    assert version == "3.2.1"
    assert freshness is Freshness.STALE


@pytest.mark.unit
def test_cache_read_missing_when_never_written() -> None:
    """A never-written cache entry reads MISSING with no version."""
    version, freshness = update_check.read_cached_version(now=1000, ttl_seconds=86400)
    assert version is None
    assert freshness is Freshness.MISSING


@pytest.mark.unit
def test_alert_emitted_when_fresh_cache_has_newer_version() -> None:
    """A FRESH cache with a newer version alerts on the injected stream (no fetch)."""
    update_check.write_cached_version("99.0.0", now=1000)
    stream = io.StringIO()
    with (
        patch.object(update_check, "installed_version", return_value="1.0.0"),
        patch.object(update_check, "is_editable_install", return_value=False),
        patch.object(update_check, "fetch_latest_version") as fetch,
    ):
        update_check.maybe_alert_update(_args(), "install", environ={}, stream=stream, now=1000 + 5)
    out = stream.getvalue()
    assert "99.0.0" in out
    assert constants.KANON_UPDATE_UPGRADE_COMMAND in out
    fetch.assert_not_called()


@pytest.mark.unit
def test_silent_when_installed_version_is_current() -> None:
    """No alert is printed when the installed version equals the latest."""
    update_check.write_cached_version("2.0.0", now=1000)
    stream = io.StringIO()
    with (
        patch.object(update_check, "installed_version", return_value="2.0.0"),
        patch.object(update_check, "is_editable_install", return_value=False),
    ):
        update_check.maybe_alert_update(_args(), "install", environ={}, stream=stream, now=1000 + 5)
    assert stream.getvalue() == ""


@pytest.mark.unit
def test_silent_when_installed_version_is_newer() -> None:
    """No alert when the installed version is newer than the cached latest."""
    update_check.write_cached_version("1.0.0", now=1000)
    stream = io.StringIO()
    with (
        patch.object(update_check, "installed_version", return_value="2.0.0"),
        patch.object(update_check, "is_editable_install", return_value=False),
    ):
        update_check.maybe_alert_update(_args(), "install", environ={}, stream=stream, now=1000 + 5)
    assert stream.getvalue() == ""


@pytest.mark.unit
def test_missing_cache_triggers_inline_fetch_and_writes() -> None:
    """A MISSING cache performs one inline fetch and persists the result."""
    stream = io.StringIO()
    with (
        patch.object(update_check, "installed_version", return_value="1.0.0"),
        patch.object(update_check, "is_editable_install", return_value=False),
        patch.object(update_check, "fetch_latest_version", return_value="5.5.5") as fetch,
    ):
        update_check.maybe_alert_update(_args(), "install", environ={}, stream=stream, now=2000)
    fetch.assert_called_once()
    assert "5.5.5" in stream.getvalue()

    version, freshness = update_check.read_cached_version(now=2000, ttl_seconds=86400)
    assert version == "5.5.5"
    assert freshness is Freshness.FRESH


@pytest.mark.unit
def test_stale_cache_serves_value_and_schedules_background_refresh() -> None:
    """A STALE cache alerts from the cached value and schedules a bg refresh, no inline fetch."""
    update_check.write_cached_version("7.0.0", now=1000)
    stream = io.StringIO()
    with (
        patch.object(update_check, "installed_version", return_value="1.0.0"),
        patch.object(update_check, "is_editable_install", return_value=False),
        patch.object(update_check, "fork_background_refresh") as bg,
        patch.object(update_check, "fetch_latest_version") as fetch,
    ):
        update_check.maybe_alert_update(_args(), "install", environ={}, stream=stream, now=1000 + 1_000_000)
    assert "7.0.0" in stream.getvalue()
    bg.assert_called_once_with(update_check._refresh_cache)
    fetch.assert_not_called()


@pytest.mark.unit
def test_graceful_fail_missing_cache_and_failed_fetch_no_alert_no_error() -> None:
    """A cold cache with a failed lookup prints no alert and raises nothing."""
    stream = io.StringIO()
    with (
        patch.object(update_check, "installed_version", return_value="1.0.0"),
        patch.object(update_check, "is_editable_install", return_value=False),
        patch.object(update_check, "fetch_latest_version", return_value=None),
    ):
        update_check.maybe_alert_update(_args(), "install", environ={}, stream=stream, now=2000)
    assert stream.getvalue() == ""


@pytest.mark.unit
def test_unparseable_latest_version_is_not_treated_as_upgrade() -> None:
    """A non-PEP-440 cached latest never triggers an alert (graceful-fail on garbage)."""
    update_check.write_cached_version("not-a-version", now=1000)
    stream = io.StringIO()
    with (
        patch.object(update_check, "installed_version", return_value="1.0.0"),
        patch.object(update_check, "is_editable_install", return_value=False),
    ):
        update_check.maybe_alert_update(_args(), "install", environ={}, stream=stream, now=1000 + 5)
    assert stream.getvalue() == ""


class _TTYStream(io.StringIO):
    """A StringIO that reports itself as a TTY for color-gating tests."""

    def isatty(self) -> bool:
        return True


@pytest.mark.unit
def test_alert_colored_on_tty_without_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """On a TTY with NO_COLOR unset, the alert is wrapped in bright-color SGR codes."""
    monkeypatch.setattr(constants, "_NO_COLOR_ACTIVE", False, raising=False)
    update_check.write_cached_version("99.0.0", now=1000)
    stream = _TTYStream()
    with (
        patch.object(update_check, "installed_version", return_value="1.0.0"),
        patch.object(update_check, "is_editable_install", return_value=False),
    ):
        update_check.maybe_alert_update(_args(), "install", environ={}, stream=stream, now=1000 + 5)
    out = stream.getvalue()
    assert constants.ANSI_BRIGHT_CYAN in out
    assert constants.ANSI_RESET in out


@pytest.mark.unit
def test_alert_not_colored_when_no_color_env_set() -> None:
    """NO_COLOR set suppresses color even on a TTY."""
    update_check.write_cached_version("99.0.0", now=1000)
    stream = _TTYStream()
    with (
        patch.object(update_check, "installed_version", return_value="1.0.0"),
        patch.object(update_check, "is_editable_install", return_value=False),
    ):
        update_check.maybe_alert_update(
            _args(),
            "install",
            environ={constants.NO_COLOR_ENV: "1"},
            stream=stream,
            now=1000 + 5,
        )
    out = stream.getvalue()
    assert "99.0.0" in out
    assert constants.ANSI_BRIGHT_CYAN not in out


@pytest.mark.unit
def test_alert_not_colored_on_non_tty_stream() -> None:
    """A non-TTY stream (pipe) gets a plain-text alert (protects piped output)."""
    update_check.write_cached_version("99.0.0", now=1000)
    stream = io.StringIO()
    with (
        patch.object(update_check, "installed_version", return_value="1.0.0"),
        patch.object(update_check, "is_editable_install", return_value=False),
    ):
        update_check.maybe_alert_update(_args(), "install", environ={}, stream=stream, now=1000 + 5)
    out = stream.getvalue()
    assert "99.0.0" in out
    assert constants.ANSI_BRIGHT_CYAN not in out


@pytest.mark.unit
def test_alert_not_colored_when_no_color_active_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """constants._NO_COLOR_ACTIVE (the --no-color flag) suppresses color on a TTY."""
    monkeypatch.setattr(constants, "_NO_COLOR_ACTIVE", True, raising=False)
    update_check.write_cached_version("99.0.0", now=1000)
    stream = _TTYStream()
    with (
        patch.object(update_check, "installed_version", return_value="1.0.0"),
        patch.object(update_check, "is_editable_install", return_value=False),
    ):
        update_check.maybe_alert_update(_args(), "install", environ={}, stream=stream, now=1000 + 5)
    assert constants.ANSI_BRIGHT_CYAN not in stream.getvalue()


@pytest.mark.unit
def test_constants_defaults_match_spec() -> None:
    """The locked spec defaults are wired through constants.py."""
    assert constants.KANON_UPDATE_CHECK_TTL == 86400
    assert constants.KANON_UPDATE_CONNECT_TIMEOUT == 2
    assert constants.KANON_UPDATE_READ_TIMEOUT == 3
    assert constants.KANON_UPDATE_BODY_SIZE_CAP == 200 * 1024
    assert constants.KANON_PYPI_JSON_URL == "https://pypi.org/pypi/kanon-cli/json"
    assert constants.KANON_UPDATE_UPGRADE_COMMAND == "pipx upgrade kanon-cli"


@pytest.mark.unit
def test_module_routes_endpoint_and_command_through_constants() -> None:
    """The operative endpoint / upgrade command / knobs come from constants.

    The endpoint default, the upgrade command, and the timeout/TTL/size-cap
    defaults must be referenced via ``constants.*`` (never inlined as a bare
    operative literal). Prose mentions in the module docstring are not operative
    values, so this asserts the constants are wired in rather than scanning the
    docstring for the human-readable strings.
    """
    import ast

    source = Path(update_check.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "constants":
            referenced.add(node.attr)

    for required in (
        "KANON_PYPI_JSON_URL",
        "KANON_UPDATE_UPGRADE_COMMAND",
        "KANON_UPDATE_CONNECT_TIMEOUT",
        "KANON_UPDATE_READ_TIMEOUT",
        "KANON_UPDATE_BODY_SIZE_CAP",
        "KANON_UPDATE_CHECK_TTL",
        "KANON_UPDATE_ALERT_TEMPLATE",
    ):
        assert required in referenced, f"update_check.py must reference constants.{required}"

    body = tree.body
    docstring_text = ""
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        value = body[0].value.value
        if isinstance(value, str):
            docstring_text = value
    operative_string_constants = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value != docstring_text
    ]
    assert all("https://pypi.org" not in s for s in operative_string_constants)
    assert all(constants.KANON_UPDATE_UPGRADE_COMMAND not in s for s in operative_string_constants)
