"""PyPI "update available" alert for the kanon CLI (spec Section 7.1 / FR-29).

This module surfaces a best-effort alert on stderr when a newer ``kanon-cli``
release is published on PyPI than the one the operator is running. It is wired
into ``kanon_cli.cli.main`` as a pre-dispatch hook so the message is shown once
per invocation before the chosen subcommand runs.

Design contract (spec Section 7.1 / Section 7.3 / Section 3.5):

- The latest published version is read from the PyPI JSON metadata endpoint
  (``constants.KANON_PYPI_JSON_URL``) with a short connect timeout
  (``KANON_UPDATE_CONNECT_TIMEOUT``, default 2s) and read timeout
  (``KANON_UPDATE_READ_TIMEOUT``, default 3s), a response-body size cap
  (``KANON_UPDATE_BODY_SIZE_CAP``, default 200KB), and an explicit
  ``User-Agent`` header. None of these values is a literal in this module; every
  one is routed through ``constants`` (and the ``_env_int`` guard there).
- The looked-up version is cached under ``<KANON_HOME>/cache/update-check`` with a
  TTL read from ``KANON_UPDATE_CHECK_TTL`` (default 86400s / 24h), reusing the
  ``completions/cache.py`` TTL primitives. When the cached entry is FRESH the
  alert is computed from it with no network call. When it is STALE the alert is
  computed from the last cached value and a background refresh is dispatched via
  ``spawn_detached`` (the same detached-spawn seam the completion cache uses);
  the foreground command never blocks on the network and uses no temporal-delay
  synchronisation and no direct process-fork. When the cached entry is MISSING an
  inline fetch is performed once so the first invocation can still alert.
- The alert is written to **stderr** (never stdout, so ``--format json`` / pipes /
  completion scripts stay clean), is colored only when stderr is a TTY and
  ``NO_COLOR`` is unset, names the available version and the
  ``pipx upgrade kanon-cli`` upgrade command, and is **silent when the installed
  version is current** (it speaks only on an available upgrade).
- A failed, timed-out, or oversized lookup prints **no alert** and **never
  errors** the command. This graceful-fail is intentional and bounded: the update
  check is a best-effort convenience, not a required operation, so a network
  problem must not turn ``kanon install`` (or any command) into a failure. Only
  the lookup/cache I/O for THIS best-effort feature is tolerated; the function
  never swallows an exception raised by the underlying command.
- The check is skipped entirely for: completion invocations (the registered
  ``__complete_*`` completer subcommands), dev/editable installs, the
  ``--no-update-check`` global flag, and ``KANON_SKIP_UPDATE_CHECK=1``.

The module is structured around small, single-responsibility helpers with the
network fetch, the installed-version probe, the editable-install probe, the
"now" clock, and the stderr stream all injectable so every branch is covered by
real, falsifiable unit tests without touching the live network or the operator's
real ``~/.kanon-home`` store.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import TextIO

from packaging.version import InvalidVersion, Version

import kanon_cli.constants as constants
from kanon_cli.completions.cache import (
    Freshness,
    cache_dir,
    fork_background_refresh,
    read_entries,
    write_entries,
    write_epoch,
)
from kanon_cli.completions.cache import classify as _classify_freshness


_COMPLETER_COMMAND_PREFIX = "__complete"


def installed_version() -> str:
    """Return the installed ``kanon-cli`` distribution version.

    Reads the version from the installed distribution metadata via
    ``importlib.metadata`` rather than from ``kanon_cli.__version__`` so the
    comparison reflects what pip/pipx actually installed.

    Returns:
        The installed version string (e.g. ``"2.1.0"``).

    Raises:
        importlib.metadata.PackageNotFoundError: If the distribution metadata is
            not present. Callers in the update-check path treat this as a
            dev/source invocation via :func:`is_editable_install` before reaching
            here, so a missing distribution is handled as a skip, not an error.
    """
    return metadata.version(constants.KANON_PYPI_PROJECT_NAME)


def is_editable_install() -> bool:
    """Return True when ``kanon-cli`` is installed as an editable/dev install.

    A pip/pipx editable install records ``direct_url.json`` with
    ``dir_info.editable == true`` in the distribution metadata; a running-from-
    source checkout with no installed distribution has no metadata at all. Both
    cases are treated as a dev install for which the update alert is skipped
    (spec Section 7.1: "Skip the check entirely for dev/editable installs").

    Returns:
        True when the distribution is missing (source checkout) or marked
        editable; False for a normal wheel/sdist install.
    """
    try:
        dist = metadata.distribution(constants.KANON_PYPI_PROJECT_NAME)
    except metadata.PackageNotFoundError:
        return True

    raw = dist.read_text("direct_url.json")
    if raw is None:
        return False
    try:
        direct_url = json.loads(raw)
    except json.JSONDecodeError:
        return False
    dir_info = direct_url.get("dir_info")
    if not isinstance(dir_info, dict):
        return False
    return bool(dir_info.get("editable", False))


def should_skip(
    args: argparse.Namespace,
    command: str | None,
    *,
    environ: "dict[str, str]",
    editable_probe: Callable[[], bool] | None = None,
) -> bool:
    """Return True when the update check must be skipped for this invocation.

    Skip conditions (spec Section 7.1), evaluated before any network or cache
    access so a skip short-circuits with zero side effects:

    - ``command`` is a registered ``__complete_*`` completer subcommand.
    - ``KANON_SKIP_UPDATE_CHECK`` is set to ``"1"``.
    - the ``--no-update-check`` global flag is set on ``args``.
    - the distribution is a dev/editable install.

    Args:
        args: The parsed argument namespace (carries ``no_update_check``).
        command: The resolved top-level command name (``args.command``), or None.
        environ: The environment mapping to read ``KANON_SKIP_UPDATE_CHECK`` from
            (injected for testability; production passes ``os.environ``).
        editable_probe: Zero-argument callable returning whether the install is
            editable. When None (the default) the module-level
            :func:`is_editable_install` is resolved at call time so a test that
            patches the module attribute is honoured (late binding).

    Returns:
        True when the check should be skipped; False when it should proceed.
    """
    if command is not None and command.startswith(_COMPLETER_COMMAND_PREFIX):
        return True

    if environ.get(constants.KANON_SKIP_UPDATE_CHECK_ENV) == constants.KANON_SKIP_UPDATE_CHECK_TRUE:
        return True

    if getattr(args, "no_update_check", False):
        return True

    probe = is_editable_install if editable_probe is None else editable_probe
    if probe():
        return True

    return False


def fetch_latest_version(
    *,
    url: str = constants.KANON_PYPI_JSON_URL,
    connect_timeout: int = constants.KANON_UPDATE_CONNECT_TIMEOUT,
    read_timeout: int = constants.KANON_UPDATE_READ_TIMEOUT,
    body_size_cap: int = constants.KANON_UPDATE_BODY_SIZE_CAP,
    user_agent: str | None = None,
) -> str | None:
    """Look up the latest published ``kanon-cli`` version on PyPI.

    Performs a single hardened HTTP GET against the PyPI JSON metadata endpoint:
    a short connect/read timeout, a response-body size cap, and an explicit
    ``User-Agent`` header. The body is read up to ``body_size_cap + 1`` bytes; if
    the cap is exceeded the lookup is abandoned and ``None`` is returned (no alert,
    no error). Any network/parse failure returns ``None`` (graceful-fail per spec
    Section 7.1: a failed lookup prints no alert and never errors the command).

    Args:
        url: The PyPI JSON endpoint (default ``constants.KANON_PYPI_JSON_URL``).
        connect_timeout: Connect timeout in seconds (urllib applies one combined
            socket timeout; the larger of connect/read is used so neither phase is
            starved). Default ``constants.KANON_UPDATE_CONNECT_TIMEOUT``.
        read_timeout: Read timeout in seconds. Default
            ``constants.KANON_UPDATE_READ_TIMEOUT``.
        body_size_cap: Maximum response-body bytes to read. Default
            ``constants.KANON_UPDATE_BODY_SIZE_CAP``.
        user_agent: Explicit ``User-Agent`` header value. When None the default
            ``"kanon-cli/<installed-version>"`` is used so PyPI sees an honest
            client identity.

    Returns:
        The latest version string from ``info.version`` on success, or ``None``
        on any timeout, oversized body, HTTP error, or malformed payload.
    """
    if user_agent is None:
        try:
            agent_version = installed_version()
        except metadata.PackageNotFoundError:
            agent_version = "source"
        user_agent = f"{constants.KANON_PYPI_PROJECT_NAME}/{agent_version}"

    socket_timeout = max(connect_timeout, read_timeout)

    if not url.lower().startswith("https://"):
        return None

    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=socket_timeout) as response:
            body = response.read(body_size_cap + 1)
    except (urllib.error.URLError, OSError, ValueError):
        return None

    if len(body) > body_size_cap:
        return None

    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    version = info.get("version")
    if not isinstance(version, str) or not version:
        return None
    return version


def _cache_entry_dir() -> Path:
    """Return the update-check cache entry directory under the shared cache root."""
    return cache_dir() / constants.KANON_UPDATE_CHECK_CACHE_SUBDIR


def read_cached_version(now: int, ttl_seconds: int) -> tuple[str | None, Freshness]:
    """Return (cached_latest_version, freshness) from the update-check cache.

    Reuses the ``completions/cache.py`` freshness machinery: the ``fetched_at.txt``
    sidecar in the entry directory is classified against ``ttl_seconds`` and the
    cached version is read from ``latest.txt`` on a FRESH/STALE hit.

    Args:
        now: Current epoch seconds (injected for testability).
        ttl_seconds: Cache TTL in seconds (``constants.KANON_UPDATE_CHECK_TTL``).

    Returns:
        A tuple of (version-or-None, Freshness). The version is None on a MISSING
        entry or an empty value file; otherwise it is the cached latest version.
    """
    entry_dir = _cache_entry_dir()
    fetched_at_path = entry_dir / "fetched_at.txt"
    freshness = _classify_freshness(fetched_at_path, ttl_seconds=ttl_seconds, now=now)
    if freshness is Freshness.MISSING:
        return None, Freshness.MISSING

    entries = read_entries(entry_dir / constants.KANON_UPDATE_CHECK_VERSION_FILENAME)
    if not entries:
        return None, freshness
    return entries[0], freshness


def write_cached_version(version: str, now: int) -> None:
    """Persist ``version`` as the latest looked-up PyPI version with TTL stamp.

    Writes the version to ``latest.txt`` and stamps ``fetched_at.txt`` with
    ``now`` inside the update-check cache entry, reusing the sanitised 0600
    ``write_entries`` / ``write_epoch`` primitives (DRY: no duplicated cache I/O).

    Args:
        version: The latest version string to cache.
        now: Current epoch seconds to record as ``fetched_at``.
    """
    entry_dir = _cache_entry_dir()
    write_entries(
        entry_dir / constants.KANON_UPDATE_CHECK_VERSION_FILENAME,
        [version],
        completer_name="update-check",
    )
    write_epoch(entry_dir / "fetched_at.txt", now)


def _refresh_cache() -> None:
    """Fetch the latest version and write it to the cache (background-refresh body).

    Run in the detached child spawned by :func:`fork_background_refresh`. A failed
    lookup writes nothing (the stale entry is left in place for the next run);
    this is the best-effort refresh contract, not a swallowed required operation.
    """
    latest = fetch_latest_version()
    if latest is None:
        return
    write_cached_version(latest, int(time.time()))


def _is_newer(latest: str, current: str) -> bool:
    """Return True when ``latest`` is a strictly newer PEP 440 version than ``current``.

    A version string that is not valid PEP 440 (either side) yields False: an
    unparseable version is never treated as an available upgrade (graceful-fail,
    no alert on garbage input).

    Args:
        latest: The latest published version string.
        current: The installed version string.

    Returns:
        True only when both parse as PEP 440 and ``latest > current``.
    """
    try:
        return Version(latest) > Version(current)
    except InvalidVersion:
        return False


def _render_alert(latest: str, current: str, *, colorize: bool) -> str:
    """Build the alert text, optionally wrapped in bright-color SGR sequences.

    Args:
        latest: The available newer version.
        current: The installed version.
        colorize: When True the message is wrapped in
            ``ANSI_BRIGHT_CYAN`` ... ``ANSI_RESET``; when False it is plain text.

    Returns:
        The rendered alert string (no trailing newline; the caller adds it).
    """
    message = constants.KANON_UPDATE_ALERT_TEMPLATE.format(
        latest=latest,
        current=current,
        command=constants.KANON_UPDATE_UPGRADE_COMMAND,
    )
    if colorize:
        return f"{constants.ANSI_BRIGHT_CYAN}{message}{constants.ANSI_RESET}"
    return message


def _should_colorize(stream: TextIO, environ: "dict[str, str]") -> bool:
    """Return True when the alert may be colored for ``stream``.

    Color is applied only when ``stream`` is a TTY and ``NO_COLOR`` is unset
    (spec Section 7.3, following the https://no-color.org convention). The
    ``constants._NO_COLOR_ACTIVE`` runtime flag (set by ``--no-color``) also
    suppresses color so the global flag is honoured.

    Args:
        stream: The output stream the alert is written to (stderr).
        environ: The environment mapping to read ``NO_COLOR`` from.

    Returns:
        True when color may be emitted; False otherwise.
    """
    if constants._NO_COLOR_ACTIVE:
        return False
    if environ.get(constants.NO_COLOR_ENV):
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def maybe_alert_update(
    args: argparse.Namespace,
    command: str | None,
    *,
    environ: "dict[str, str]",
    stream: TextIO | None = None,
    now: int | None = None,
) -> None:
    """Emit the update-available alert on stderr, honouring every skip condition.

    This is the pre-dispatch hook wired into ``cli.main``. It applies the skip
    gate first, then resolves the latest version from the TTL cache (falling back
    to a single inline fetch on a cache miss and scheduling a detached background
    refresh on a stale hit), compares it against the installed version, and writes
    a single colored-when-TTY alert to stderr only when a strictly newer version
    is available. Any lookup/cache failure is swallowed for this best-effort
    feature so the foreground command is never disturbed.

    Args:
        args: The parsed argument namespace (carries ``no_update_check``).
        command: The resolved top-level command name (``args.command``), or None.
        environ: The environment mapping (production passes ``os.environ``).
        stream: The stream to write the alert to. Defaults to ``sys.stderr``.
        now: Current epoch seconds. Defaults to ``int(time.time())``.
    """
    if should_skip(args, command, environ=environ):
        return

    out = sys.stderr if stream is None else stream
    current_epoch = int(time.time()) if now is None else now

    try:
        current = installed_version()
    except metadata.PackageNotFoundError:
        return

    latest, freshness = read_cached_version(current_epoch, constants.KANON_UPDATE_CHECK_TTL)

    if freshness is Freshness.MISSING:
        latest = fetch_latest_version()
        if latest is not None:
            write_cached_version(latest, current_epoch)
    elif freshness is Freshness.STALE:
        fork_background_refresh(_refresh_cache)

    if latest is None:
        return

    if not _is_newer(latest, current):
        return

    colorize = _should_colorize(out, environ)
    out.write(_render_alert(latest, current, colorize=colorize) + "\n")
