"""Usage-telemetry emitter for the kanon CLI (modeled on ``core/update_check.py``).

This module emits one structured usage event per dispatched command to the
Caylent telemetry collector. It is wired into ``kanon_cli.cli.main`` as a
``try/finally`` hook around subcommand dispatch so the event is fired after the
command runs, capturing the resolved command, its outcome (exit code, status,
exception class, duration), the runtime environment, credential-stripped git
provenance, and -- for ``kanon install`` -- the complete resolved install graph
(every direct source and every transitive repo package with its source URL and
resolved content SHA).

Design contract:

- **Auto opted-in.** Telemetry is ON out of the box for every user; there is no
  opt-in prompt, no consent gate, and no enable toggle. The ONLY way it is off
  is the operator setting ``KANON_TELEMETRY_DISABLED`` (env var only; there is no
  ``--no-telemetry`` flag). Completion invocations, editable/dev/source installs,
  and the opt-out env var are all skipped via :func:`should_skip`.
- **Non-blocking, silent, never-fail.** The event payload is built in the
  foreground (local git + lockfile reads only, no network) and the actual HTTPS
  POST is fired in a detached child via ``utils.spawn.spawn_detached`` (stdout ->
  ``/dev/null``, errors -> a background telemetry error log). The user's command
  is never blocked, delayed on the network, nor failed by any telemetry error.
- **Zero secrets.** Only an explicit allowlist of kanon-computed fields is
  serialized. Raw argv is never emitted; SSH/private keys, tokens, credentials,
  key files, ``~/.ssh``, env-var values, and file contents are never read or
  emitted. Every URL is credential-stripped (any ``user:pass@`` / ``token@``
  userinfo is dropped, host + org + repo kept) before it is serialized.
- **Structured OTLP-logs JSON.** One log record whose ``body.stringValue`` is a
  flat JSON object with the four top-level keys ``tool`` / ``timestamp`` /
  ``event_type`` / ``payload`` (the collector stores the record body verbatim via
  ``raw_log = true`` and the Firehose maps those four keys to Glue string
  columns). ``payload`` is a JSON-encoded string carrying the rich structured
  fields. The full install graph is capped well under the collector's body limit;
  if it would exceed the cap it is dropped in favour of the flattened
  ``installed_packages`` summary with ``install_graph_truncated: true``.

All literals (endpoints, env-var names, timeouts, size caps, event/tool names)
are routed through ``constants`` and every network/spawn/clock seam is injectable
so the whole module is covered by real, falsifiable unit tests without touching
the live collector, the operator's real git config, or forking a real process.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import time
import traceback
import urllib.request
import uuid
from collections.abc import Callable
from functools import partial
from importlib import metadata
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit, urlunsplit

import kanon_cli.constants as constants
from kanon_cli.completions.cache import cache_dir
from kanon_cli.core.lockfile import Lockfile, LockfileSchemaError, LockfileValidationError, read_lockfile
from kanon_cli.core.update_check import installed_version, is_editable_install
from kanon_cli.core.url import canonicalize_repo_url
from kanon_cli.utils.lock_file_path import derive_lock_file_path
from kanon_cli.utils.spawn import spawn_detached


_SCP_URL_RE = re.compile(r"^(?P<user>[^@/:]+@)?(?P<host>[^@/:]+):(?P<path>.+)$")


_SCHEME_URL_PREFIXES = ("https://", "http://", "ssh://", "git://", "ftp://", "ftps://")


def _is_truthy(value: str | None) -> bool:
    """Return True when ``value`` is a recognised truthy token (case-insensitive).

    The recognised tokens are ``constants.KANON_TELEMETRY_TRUTHY_VALUES``
    (``1``/``true``/``yes``/``on``). ``None``, the empty string, and any other
    value (including ``0``/``false``) are falsey.

    Args:
        value: The raw environment-variable value to classify, or ``None``.

    Returns:
        True when ``value`` names a truthy token; False otherwise.
    """
    if value is None:
        return False
    return value.strip().lower() in constants.KANON_TELEMETRY_TRUTHY_VALUES


def is_disabled(environ: "dict[str, str]") -> bool:
    """Return True when telemetry is disabled via the opt-out env var.

    ``KANON_TELEMETRY_DISABLED`` is the single, operator-only opt-out. Any truthy
    value disables telemetry for the invocation.

    Args:
        environ: The environment mapping (production passes ``os.environ``).

    Returns:
        True when the opt-out env var is set to a truthy value.
    """
    return _is_truthy(environ.get(constants.KANON_TELEMETRY_DISABLED_ENV))


def is_forced(environ: "dict[str, str]") -> bool:
    """Return True when telemetry is force-enabled for a dev/editable install.

    ``KANON_TELEMETRY_FORCE`` is an internal testing/diagnostic override: when
    truthy it bypasses ONLY the editable/dev/source-install skip so a telemetry
    event can be exercised end to end from a source checkout. It never overrides
    the ``KANON_TELEMETRY_DISABLED`` opt-out or the completion-subcommand skip,
    both of which are evaluated first.

    Args:
        environ: The environment mapping (production passes ``os.environ``).

    Returns:
        True when the force override is set to a truthy value.
    """
    return _is_truthy(environ.get(constants.KANON_TELEMETRY_FORCE_ENV))


def is_debug(args: argparse.Namespace, environ: "dict[str, str]") -> bool:
    """Return True when the would-send JSON should be printed to stderr.

    Debug mode is enabled by the ``--telemetry-debug`` global flag or the
    ``KANON_TELEMETRY_DEBUG`` env var (either truthy value). It prints the exact
    request body without changing the non-blocking send behaviour.

    Args:
        args: The parsed argument namespace (carries ``telemetry_debug``).
        environ: The environment mapping (production passes ``os.environ``).

    Returns:
        True when debug output is requested.
    """
    if getattr(args, "telemetry_debug", False):
        return True
    return _is_truthy(environ.get(constants.KANON_TELEMETRY_DEBUG_ENV))


def should_skip(
    args: argparse.Namespace,
    command: str | None,
    *,
    environ: "dict[str, str]",
    editable_probe: Callable[[], bool] | None = None,
) -> bool:
    """Return True when telemetry must be skipped for this invocation.

    Skip precedence (evaluated before any git/lockfile/network work so a skip
    short-circuits with zero side effects):

    - ``KANON_TELEMETRY_DISABLED`` is set truthy (the operator opt-out; wins over
      everything).
    - ``command`` is a registered ``__complete*`` completer subcommand.
    - ``KANON_TELEMETRY_FORCE`` is set truthy -> do NOT skip (the dev/editable
      override; used by tests to exercise the real path from a source checkout).
    - the distribution is a dev/editable/source install.

    Args:
        args: The parsed argument namespace.
        command: The resolved top-level command name (``args.command``), or None.
        environ: The environment mapping (production passes ``os.environ``).
        editable_probe: Zero-argument callable returning whether the install is
            editable. When None (the default) the module-level
            :func:`is_editable_install` is resolved at call time so a test that
            patches the attribute is honoured (late binding).

    Returns:
        True when telemetry should be skipped; False when it should proceed.
    """
    if is_disabled(environ):
        return True

    if command is not None and command.startswith(constants.KANON_COMPLETER_COMMAND_PREFIX):
        return True

    if is_forced(environ):
        return False

    probe = is_editable_install if editable_probe is None else editable_probe
    if probe():
        return True

    return False


def resolve_endpoint(args: argparse.Namespace, environ: "dict[str, str]") -> str:
    """Resolve the collector endpoint using the flag > env > default precedence.

    Args:
        args: The parsed argument namespace (carries ``telemetry_endpoint``).
        environ: The environment mapping (production passes ``os.environ``).

    Returns:
        The resolved collector endpoint URL. Precedence (highest first): the
        ``--telemetry-endpoint`` flag, the ``KANON_TELEMETRY_ENDPOINT`` env var,
        then ``constants.KANON_TELEMETRY_ENDPOINT_DEFAULT``.
    """
    flag_value = getattr(args, "telemetry_endpoint", None)
    if flag_value:
        return str(flag_value)
    env_value = environ.get(constants.KANON_TELEMETRY_ENDPOINT_ENV)
    if env_value:
        return env_value
    return constants.KANON_TELEMETRY_ENDPOINT_DEFAULT


def strip_url_credentials(url: str | None) -> str | None:
    """Return ``url`` with any embedded credentials removed, or None if unusable.

    Drops any ``user:pass@`` / ``token@`` userinfo from the authority and any
    query string or fragment, preserving the scheme, host, port, and path so the
    host + org + repo remain intact. Handles ``https``/``http``/``ssh``/``git``
    scheme URLs and ``[user@]host:path`` SCP shorthand. Any input that cannot be
    parsed into a recognised shape returns ``None`` -- the emitter drops the field
    rather than risk serialising an unparsed value that might carry a secret.

    Args:
        url: The raw URL to sanitise, or ``None``.

    Returns:
        The credential-stripped URL, or ``None`` when the input is empty or not a
        recognised URL shape.
    """
    if not url or not url.strip():
        return None
    stripped = url.strip()

    if stripped.lower().startswith(_SCHEME_URL_PREFIXES):
        parts = urlsplit(stripped)
        host = parts.hostname or ""
        if not host:
            return None
        authority = f"{host}:{parts.port}" if parts.port else host
        return urlunsplit((parts.scheme, authority, parts.path, "", ""))

    match = _SCP_URL_RE.match(stripped)
    if match is not None:
        return f"{match.group('host')}:{match.group('path')}"

    return None


def _split_repo_url(clean_url: str | None) -> tuple[str | None, str | None, str | None]:
    """Return ``(host, org, repo)`` parsed from a credential-stripped repo URL.

    The URL is canonicalized to ``https://host/path`` (which also strips any
    residual userinfo) before the path is split: the last path segment (minus a
    trailing ``.git``) is the repo, everything before it is the org (which may
    contain nested groups joined by ``/``), and the authority is the host.

    Args:
        clean_url: A credential-stripped repo URL, or ``None``.

    Returns:
        A ``(host, org, repo)`` tuple. Any component that cannot be determined is
        ``None``.
    """
    if not clean_url:
        return None, None, None
    try:
        canonical = canonicalize_repo_url(clean_url)
    except ValueError:
        return None, None, None
    parts = urlsplit(canonical)
    host = parts.hostname
    path = parts.path.strip("/")
    if not path:
        return host, None, None
    segments = path.split("/")
    repo = segments[-1]
    org = "/".join(segments[:-1]) or None
    return host, org, repo


def _run_git(git_args: list[str], *, cwd: Path, timeout: int) -> str | None:
    """Run a read-only ``git`` command and return its stripped stdout, or None.

    Best-effort: any non-zero exit, timeout, or missing-git error yields ``None``
    (the field is simply omitted from the payload). ``check=False`` and a bounded
    timeout guarantee the foreground command is never blocked or failed by a git
    probe. Only read-only sub-commands (``config --get``, ``rev-parse``) are ever
    passed here; no user input is interpolated into the argument vector.

    Args:
        git_args: The ``git`` sub-command argument vector (without the ``git``).
        cwd: The working directory to run git in.
        timeout: Maximum seconds to wait for git before giving up.

    Returns:
        The command's stdout stripped of surrounding whitespace, or ``None`` on
        any failure / empty output.
    """
    try:
        result = subprocess.run(
            ["git", *git_args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def collect_git_metadata(cwd: Path, *, timeout: int) -> dict[str, Any]:
    """Collect credential-stripped git provenance for the working directory.

    Reads the committer email (``git config --get user.email``), the ``origin``
    remote URL (``git config --get remote.origin.url``), and the current branch
    (``git rev-parse --abbrev-ref HEAD``). The remote URL is credential-stripped
    and split into host / org / repo; the raw remote URL is never emitted. Every
    probe is best-effort: a non-git directory or a missing value simply omits that
    key. No private key, token, credential, or file content is ever read.

    Args:
        cwd: The working directory to probe (production passes the process cwd).
        timeout: Per-git-command timeout in seconds.

    Returns:
        A dict with any resolvable subset of ``user_email``, ``remote_host``,
        ``org``, ``repo``, and ``branch``. An empty dict when the directory is not
        a git repository.
    """
    metadata_out: dict[str, Any] = {}

    email = _run_git(["config", "--get", "user.email"], cwd=cwd, timeout=timeout)
    if email is not None:
        metadata_out["user_email"] = email

    remote = _run_git(["config", "--get", "remote.origin.url"], cwd=cwd, timeout=timeout)
    clean_remote = strip_url_credentials(remote)
    if clean_remote is not None:
        host, org, repo = _split_repo_url(clean_remote)
        if host is not None:
            metadata_out["remote_host"] = host
        if org is not None:
            metadata_out["org"] = org
        if repo is not None:
            metadata_out["repo"] = repo

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, timeout=timeout)
    if branch is not None:
        metadata_out["branch"] = branch

    return metadata_out


def _install_type(editable_probe: Callable[[], bool]) -> str:
    """Classify the kanon-cli install as wheel, editable, or source.

    Args:
        editable_probe: Zero-argument callable returning whether the install is
            editable (injected for testability).

    Returns:
        ``constants.KANON_TELEMETRY_INSTALL_TYPE_SOURCE`` when no distribution
        metadata is present (a running-from-source checkout),
        ``...INSTALL_TYPE_EDITABLE`` for an editable install, otherwise
        ``...INSTALL_TYPE_WHEEL``.
    """
    try:
        metadata.distribution(constants.KANON_PYPI_PROJECT_NAME)
    except metadata.PackageNotFoundError:
        return constants.KANON_TELEMETRY_INSTALL_TYPE_SOURCE
    if editable_probe():
        return constants.KANON_TELEMETRY_INSTALL_TYPE_EDITABLE
    return constants.KANON_TELEMETRY_INSTALL_TYPE_WHEEL


def collect_environment(environ: "dict[str, str]", *, editable_probe: Callable[[], bool]) -> dict[str, Any]:
    """Collect the non-sensitive runtime environment descriptor.

    Args:
        environ: The environment mapping (production passes ``os.environ``).
        editable_probe: Zero-argument callable returning whether the install is
            editable (used to classify ``install_type``).

    Returns:
        A dict with ``kanon_version`` (or ``None`` for a source checkout),
        ``python_version``, ``os``, ``arch``, ``install_type``, and ``is_ci``.
        No hostname, username, or path is included.
    """
    try:
        version: str | None = installed_version()
    except metadata.PackageNotFoundError:
        version = None

    return {
        "kanon_version": version,
        "python_version": platform.python_version(),
        "os": platform.system(),
        "arch": platform.machine(),
        "install_type": _install_type(editable_probe),
        "is_ci": _is_truthy(environ.get(constants.KANON_CI_ENV)),
    }


def collect_invocation(args: argparse.Namespace, command: str | None) -> dict[str, Any]:
    """Collect the command, subcommand, boolean flag names, and allowlisted values.

    Never emits raw argv. Only argparse-computed identifiers and closed-domain
    values are serialised:

    - ``command``: the resolved top-level command name (a closed set).
    - ``subcommand``: the resolved second-level command for grouped commands
        (the ``*_command`` dest -- a closed set), or ``None``.
    - ``flags``: the sorted NAMES of the boolean flags set to ``True`` (names
        only, never their values).
    - ``flag_values``: ``{dest: value}`` for the explicit
        ``KANON_TELEMETRY_FLAG_VALUE_ALLOWLIST`` of closed-domain dests only (e.g.
        ``format``). Free-form string values (paths, URLs, names, targets) are
        never emitted.

    Args:
        args: The parsed argument namespace.
        command: The resolved top-level command name (``args.command``), or None.

    Returns:
        The invocation descriptor dict.
    """
    namespace = vars(args)

    subcommand: str | None = None
    for key in sorted(namespace):
        if key == "command" or not key.endswith("_command"):
            continue
        value = namespace[key]
        if isinstance(value, str) and value:
            subcommand = value
            break

    flags = sorted(
        key
        for key, value in namespace.items()
        if key not in constants.KANON_TELEMETRY_INTERNAL_ARG_KEYS and isinstance(value, bool) and value
    )

    flag_values: dict[str, Any] = {}
    for key in constants.KANON_TELEMETRY_FLAG_VALUE_ALLOWLIST:
        if key in namespace:
            value = namespace[key]
            if isinstance(value, (bool, int, str)) and value is not None:
                flag_values[key] = value

    return {
        "command": command,
        "subcommand": subcommand,
        "flags": flags,
        "flag_values": flag_values,
    }


def _project_to_payload(project: Any) -> dict[str, Any]:
    """Return the credential-stripped telemetry dict for one lockfile project.

    Args:
        project: A ``ProjectEntry`` from a parsed lockfile source.

    Returns:
        A dict with the project's ``name``, credential-stripped ``url``,
        ``canonical_url``, ``resolved_ref``, ``resolved_sha``, and the
        transitive scope tag.
    """
    return {
        "name": project.name,
        "url": strip_url_credentials(project.url),
        "canonical_url": project.canonical_url,
        "resolved_ref": project.resolved_ref,
        "resolved_sha": project.resolved_sha,
        "scope": constants.KANON_TELEMETRY_SCOPE_TRANSITIVE,
    }


def _flatten_includes(includes: list[Any]) -> list[dict[str, Any]]:
    """Flatten a recursive lockfile include chain into credential-stripped dicts.

    Args:
        includes: The ``IncludeEntry`` list from a lockfile source (recursive).

    Returns:
        A flat list of ``{name, path_in_repo, url, resolved_sha}`` dicts in
        depth-first order, with every include URL credential-stripped.
    """
    flat: list[dict[str, Any]] = []
    for entry in includes:
        flat.append(
            {
                "name": entry.name,
                "path_in_repo": entry.path_in_repo,
                "url": strip_url_credentials(entry.url),
                "resolved_sha": entry.resolved_sha,
            }
        )
        if entry.includes:
            flat.extend(_flatten_includes(entry.includes))
    return flat


def build_install_graph(lockfile: Lockfile) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build the structured install graph and the flattened installed-packages list.

    Args:
        lockfile: A parsed ``Lockfile`` (the install-written ``.kanon.lock``).

    Returns:
        A ``(install_graph, installed_packages)`` tuple. ``install_graph`` carries
        ``lock_schema_version``, ``generator``, and per-direct-source
        ``{alias, name, manifest_url, ref_spec, resolved_ref, resolved_sha,
        registered_marketplaces, projects[], include_chain[]}``. ``installed_packages``
        is the flattened list of every direct source (``scope: "direct"``) and
        every transitive project (``scope: "transitive"``, one per resolved
        project plus one per content pin whose remote URL could not be resolved,
        so no synced package is ever dropped). Every URL is credential-stripped.
    """
    graph_sources: list[dict[str, Any]] = []
    installed_packages: list[dict[str, Any]] = []

    for source in lockfile.sources:
        source_url = strip_url_credentials(source.url)
        installed_packages.append(
            {
                "name": source.name,
                "url": source_url,
                "sha": source.resolved_sha,
                "scope": constants.KANON_TELEMETRY_SCOPE_DIRECT,
            }
        )

        project_payloads = [_project_to_payload(project) for project in source.projects]
        project_names = {project.name for project in source.projects}

        for project in project_payloads:
            installed_packages.append(
                {
                    "name": project["name"],
                    "url": project["url"],
                    "sha": project["resolved_sha"],
                    "scope": constants.KANON_TELEMETRY_SCOPE_TRANSITIVE,
                }
            )

        for pin in source.content_pins:
            if pin.name in project_names:
                continue
            installed_packages.append(
                {
                    "name": pin.name,
                    "url": None,
                    "sha": pin.resolved_sha,
                    "scope": constants.KANON_TELEMETRY_SCOPE_TRANSITIVE,
                }
            )

        graph_sources.append(
            {
                "alias": source.alias,
                "name": source.name,
                "manifest_url": source_url,
                "ref_spec": source.ref_spec,
                "resolved_ref": source.resolved_ref,
                "resolved_sha": source.resolved_sha,
                "registered_marketplaces": list(source.registered_marketplaces),
                "projects": project_payloads,
                "include_chain": _flatten_includes(source.includes),
            }
        )

    install_graph = {
        "lock_schema_version": lockfile.schema_version,
        "generator": lockfile.generator,
        "sources": graph_sources,
    }
    return install_graph, installed_packages


def _read_install_lockfile(args: argparse.Namespace, environ: "dict[str, str]") -> Lockfile | None:
    """Read the install-written lockfile for the current invocation, or None.

    Resolves the lockfile path from the same inputs ``kanon install`` uses
    (``args.kanonenv_path`` set by the install handler after resolution, plus the
    ``--lock-file`` flag and ``KANON_LOCK_FILE`` env var) via
    ``derive_lock_file_path``, and parses it when present. Best-effort: a missing,
    unreadable, or schema-incompatible lockfile yields ``None`` (the graph is
    simply omitted).

    Args:
        args: The parsed argument namespace (carries ``kanonenv_path`` /
            ``lock_file`` after the install handler ran).
        environ: The environment mapping (production passes ``os.environ``).

    Returns:
        The parsed ``Lockfile``, or ``None`` when it is absent or unparseable.
    """
    kanonenv_path = getattr(args, "kanonenv_path", None)
    if kanonenv_path is None:
        return None
    lock_path = derive_lock_file_path(
        Path(kanonenv_path),
        getattr(args, "lock_file", None),
        environ.get(constants.KANON_LOCK_FILE),
    )
    if not lock_path.exists():
        return None
    try:
        return read_lockfile(lock_path)
    except (LockfileSchemaError, LockfileValidationError, OSError, KeyError, ValueError):
        return None


def build_payload(
    args: argparse.Namespace,
    command: str | None,
    *,
    exit_code: int,
    error_type: str | None,
    duration_ms: int,
    environ: "dict[str, str]",
    run_id: str,
    cwd: Path,
    editable_probe: Callable[[], bool],
) -> dict[str, Any]:
    """Assemble the full structured telemetry payload for one invocation.

    The payload carries the schema version, per-invocation ``run_id``, the runtime
    environment descriptor, the invocation descriptor (command/subcommand/flags),
    the outcome (exit code, status, error class, duration), credential-stripped
    git provenance, and -- for an ``install`` command with a readable lockfile --
    the install graph and the flattened ``installed_packages`` list. The install
    graph is dropped (with ``install_graph_truncated: true``) when its serialised
    size exceeds ``constants.KANON_TELEMETRY_GRAPH_SIZE_CAP`` so the body stays
    well under the collector's limit while never dropping the installed-packages
    summary.

    Args:
        args: The parsed argument namespace.
        command: The resolved top-level command name (``args.command``), or None.
        exit_code: The command's effective exit code (0 on success).
        error_type: The captured exception class name, or ``None``.
        duration_ms: The dispatch duration in milliseconds.
        environ: The environment mapping (production passes ``os.environ``).
        run_id: A per-invocation random identifier (never a device id).
        cwd: The working directory for git provenance.
        editable_probe: Zero-argument editable-install probe (injected for tests).

    Returns:
        The fully assembled payload dict.
    """
    status = constants.KANON_TELEMETRY_STATUS_OK if exit_code == 0 else constants.KANON_TELEMETRY_STATUS_ERROR

    payload: dict[str, Any] = {
        "schema_version": constants.KANON_TELEMETRY_SCHEMA_VERSION,
        "run_id": run_id,
        "environment": collect_environment(environ, editable_probe=editable_probe),
        "invocation": collect_invocation(args, command),
        "outcome": {
            "exit_code": exit_code,
            "status": status,
            "error_type": error_type,
            "duration_ms": duration_ms,
        },
        "git": collect_git_metadata(cwd, timeout=constants.KANON_TELEMETRY_GIT_TIMEOUT),
    }

    if command in constants.KANON_TELEMETRY_INSTALL_COMMANDS:
        lockfile = _read_install_lockfile(args, environ)
        if lockfile is not None:
            install_graph, installed_packages = build_install_graph(lockfile)
            payload["installed_packages"] = installed_packages
            graph_bytes = len(json.dumps(install_graph, separators=(",", ":")).encode("utf-8"))
            if graph_bytes > constants.KANON_TELEMETRY_GRAPH_SIZE_CAP:
                payload["install_graph_truncated"] = True
            else:
                payload["install_graph"] = install_graph

    return payload


def _serialize_body(payload: dict[str, Any], timestamp_iso: str) -> str:
    """Serialise the flat collector body (tool/timestamp/event_type/payload).

    ``payload`` is JSON-encoded into a STRING value so the collector's Glue
    ``payload`` string column ("Raw JSON payload") maps cleanly; the outer object
    carries only the four top-level keys the collector partitions and columns on.

    Args:
        payload: The structured payload dict.
        timestamp_iso: The ISO-8601 UTC timestamp (``...Z``) for the event.

    Returns:
        The compact JSON string used as the log record body.
    """
    body = {
        "tool": constants.KANON_TELEMETRY_TOOL_NAME,
        "timestamp": timestamp_iso,
        "event_type": constants.KANON_TELEMETRY_EVENT_TYPE,
        "payload": json.dumps(payload, separators=(",", ":"), sort_keys=True),
    }
    return json.dumps(body, separators=(",", ":"), sort_keys=True)


def _cap_body(payload: dict[str, Any], timestamp_iso: str) -> str:
    """Serialise the body, dropping the heavy graph fields if it exceeds the cap.

    Final safety net beyond the per-graph cap in :func:`build_payload`: if the
    serialised body still exceeds ``constants.KANON_TELEMETRY_MAX_BODY_BYTES``
    (e.g. a pathologically large ``installed_packages`` list), the install graph
    and installed-packages list are dropped, ``install_graph_truncated`` is set,
    and an ``installed_packages_count`` is retained so the fact that packages were
    installed is never lost.

    Args:
        payload: The structured payload dict (mutated to record truncation).
        timestamp_iso: The ISO-8601 UTC timestamp for the event.

    Returns:
        The final compact JSON body string, guaranteed within the body cap unless
        the base payload alone already exceeds it.
    """
    body_str = _serialize_body(payload, timestamp_iso)
    if len(body_str.encode("utf-8")) <= constants.KANON_TELEMETRY_MAX_BODY_BYTES:
        return body_str

    package_count = len(payload.get("installed_packages", []))
    payload.pop("install_graph", None)
    payload.pop("installed_packages", None)
    payload["install_graph_truncated"] = True
    payload["installed_packages_count"] = package_count
    return _serialize_body(payload, timestamp_iso)


def build_otlp_request(body_str: str, *, timestamp_ns: int, resource_version: str | None) -> dict[str, Any]:
    """Wrap a body string in a minimal OTLP/HTTP logs JSON request.

    The single log record's ``body.stringValue`` is the flat collector body; the
    collector stores exactly that string (``raw_log = true``). The resource and
    scope carry only the static service identity and version -- no host, user, or
    request-specific attribute.

    Args:
        body_str: The flat collector body JSON string.
        timestamp_ns: The event time in Unix nanoseconds.
        resource_version: The kanon-cli version for the scope, or ``None``.

    Returns:
        The OTLP logs request dict ready for ``json.dumps``.
    """
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": constants.KANON_TELEMETRY_SERVICE_NAME},
                        }
                    ]
                },
                "scopeLogs": [
                    {
                        "scope": {
                            "name": constants.KANON_TELEMETRY_SERVICE_NAME,
                            "version": resource_version or "",
                        },
                        "logRecords": [
                            {
                                "timeUnixNano": str(timestamp_ns),
                                "observedTimeUnixNano": str(timestamp_ns),
                                "severityNumber": 9,
                                "severityText": "INFO",
                                "body": {"stringValue": body_str},
                            }
                        ],
                    }
                ],
            }
        ]
    }


def post_telemetry(
    otlp_bytes: bytes,
    *,
    endpoint: str,
    connect_timeout: int,
    read_timeout: int,
    user_agent: str,
) -> None:
    """POST a serialised OTLP logs request to the collector over HTTPS.

    Enforces an HTTPS-only guard (a non-HTTPS endpoint raises ``ValueError`` and
    nothing is sent), sets an explicit ``Content-Type`` and ``User-Agent``, and
    applies a bounded socket timeout. Runs only in the detached child spawned by
    :func:`emit`; any network error propagates so the child records it in the
    background telemetry error log (it never reaches the foreground command).

    Args:
        otlp_bytes: The UTF-8-encoded OTLP logs request body.
        endpoint: The collector endpoint URL (must be ``https://``).
        connect_timeout: Connect timeout in seconds.
        read_timeout: Read timeout in seconds.
        user_agent: The explicit ``User-Agent`` header value.

    Raises:
        ValueError: If ``endpoint`` is not an ``https://`` URL.
        urllib.error.URLError: On any transport failure (recorded by the child).
    """
    if not endpoint.lower().startswith("https://"):
        raise ValueError(f"telemetry endpoint must be https://; got {endpoint!r}")

    request = urllib.request.Request(
        endpoint,
        data=otlp_bytes,
        headers={
            "Content-Type": constants.KANON_TELEMETRY_CONTENT_TYPE,
            "User-Agent": user_agent,
        },
        method="POST",
    )
    socket_timeout = max(connect_timeout, read_timeout)
    with urllib.request.urlopen(request, timeout=socket_timeout) as response:
        response.read(0)


def _error_log_path(environ: "dict[str, str]") -> Path:
    """Return the background telemetry error-log path.

    Uses ``KANON_TELEMETRY_LOG`` when set, otherwise
    ``cache_dir() / KANON_TELEMETRY_ERROR_LOG_FILENAME`` under the shared kanon
    home cache root.

    Args:
        environ: The environment mapping (production passes ``os.environ``).

    Returns:
        The resolved error-log path for the detached child's stderr.
    """
    override = environ.get(constants.KANON_TELEMETRY_LOG_ENV)
    if override:
        return Path(override)
    return cache_dir() / constants.KANON_TELEMETRY_ERROR_LOG_FILENAME


def _user_agent() -> str:
    """Return the explicit telemetry ``User-Agent`` header value.

    Returns:
        ``"<project>/<installed-version>"`` (e.g. ``kanon-cli/3.3.0``), or
        ``"<project>/source"`` for a running-from-source checkout.
    """
    try:
        version = installed_version()
    except metadata.PackageNotFoundError:
        version = "source"
    return f"{constants.KANON_PYPI_PROJECT_NAME}/{version}"


def maybe_emit_telemetry(
    args: argparse.Namespace,
    command: str | None,
    *,
    exit_code: int,
    error_type: str | None,
    duration_ms: int,
    environ: "dict[str, str]",
    now: float | None = None,
    cwd: Path | None = None,
    stream: TextIO | None = None,
    spawn: Callable[..., None] | None = None,
) -> None:
    """Emit the usage-telemetry event, honouring every skip condition, never failing.

    This is the ``try/finally`` hook wired into ``cli.main`` around dispatch. It
    applies the skip gate first, then builds the structured payload in the
    foreground (local git + lockfile reads only), optionally prints the exact
    would-send JSON to stderr in debug mode, and fires the HTTPS POST in a
    detached child so the user's command is never blocked, delayed on the network,
    or failed. The entire body is wrapped so ANY telemetry error (payload build,
    serialisation, or spawn) is swallowed for this best-effort feature and, where
    possible, recorded in the background error log.

    Args:
        args: The parsed argument namespace.
        command: The resolved top-level command name (``args.command``), or None.
        exit_code: The command's effective exit code (0 on success).
        error_type: The captured exception class name, or ``None``.
        duration_ms: The dispatch duration in milliseconds.
        environ: The environment mapping (production passes ``os.environ``).
        now: Current epoch seconds (defaults to ``time.time()``; injectable).
        cwd: The working directory for git provenance (defaults to ``Path.cwd()``).
        stream: The stream for debug output (defaults to ``sys.stderr``).
        spawn: The detached-spawn seam ``(fn, *, log_path)`` (defaults to
            ``spawn_detached``; tests inject a synchronous stand-in).
    """
    try:
        if should_skip(args, command, environ=environ):
            return

        current_time = time.time() if now is None else now
        timestamp_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(current_time))
        timestamp_ns = int(current_time * 1_000_000_000)
        work_dir = Path.cwd() if cwd is None else cwd

        payload = build_payload(
            args,
            command,
            exit_code=exit_code,
            error_type=error_type,
            duration_ms=duration_ms,
            environ=environ,
            run_id=uuid.uuid4().hex,
            cwd=work_dir,
            editable_probe=is_editable_install,
        )

        body_str = _cap_body(payload, timestamp_iso)

        try:
            resource_version: str | None = installed_version()
        except metadata.PackageNotFoundError:
            resource_version = None

        otlp = build_otlp_request(body_str, timestamp_ns=timestamp_ns, resource_version=resource_version)
        otlp_bytes = json.dumps(otlp, separators=(",", ":")).encode("utf-8")

        if is_debug(args, environ):
            out = sys.stderr if stream is None else stream
            out.write(json.dumps(otlp, indent=2, sort_keys=True) + "\n")

        endpoint = resolve_endpoint(args, environ)
        spawn_fn = spawn_detached if spawn is None else spawn
        spawn_fn(
            partial(
                post_telemetry,
                otlp_bytes,
                endpoint=endpoint,
                connect_timeout=constants.KANON_TELEMETRY_CONNECT_TIMEOUT,
                read_timeout=constants.KANON_TELEMETRY_READ_TIMEOUT,
                user_agent=_user_agent(),
            ),
            log_path=_error_log_path(environ),
        )
    except Exception:
        _record_foreground_error(environ)


def early_exit_command(argv: list[str]) -> str:
    """Derive the telemetry command label for a parse-time early exit.

    Argparse resolves ``--version`` and ``--help`` (and its ``-h`` alias) by
    raising ``SystemExit`` from inside ``parse_args`` before the dispatch hook can
    run, and a bare ``kanon`` invocation (no subcommand) exits before dispatch as
    well. This maps the raw argument vector to the closed-set command label
    recorded for those early exits: the first ``--version`` or ``--help`` / ``-h``
    token encountered (mirroring argparse's left-to-right action resolution), or
    :data:`constants.KANON_TELEMETRY_EARLY_EXIT_COMMAND` when neither is present
    (a bare or usage-error invocation).

    Args:
        argv: The raw argument vector (``sys.argv[1:]`` in production).

    Returns:
        ``"--version"``, ``"--help"``, or the bare/no-subcommand sentinel.
    """
    for token in argv:
        if token == constants.KANON_TELEMETRY_VERSION_COMMAND:
            return constants.KANON_TELEMETRY_VERSION_COMMAND
        if token in constants.KANON_TELEMETRY_HELP_TOKENS:
            return constants.KANON_TELEMETRY_HELP_COMMAND
    return constants.KANON_TELEMETRY_EARLY_EXIT_COMMAND


def _argv_option_value(argv: list[str], option: str) -> str | None:
    """Return the value of an ``--option value`` / ``--option=value`` flag in argv.

    Scans the raw argument vector for ``option`` in either the space-separated or
    ``=``-joined form and returns the last occurrence's value (argparse's
    last-wins semantics for a single-valued option), or ``None`` when the option
    is absent. Used to recover the ``--telemetry-endpoint`` override on a
    parse-time early exit, where ``parse_args`` aborted before populating a
    namespace.

    Args:
        argv: The raw argument vector.
        option: The long-form option string to search for.

    Returns:
        The recovered value, or ``None`` when the option is not present.
    """
    prefix = f"{option}="
    value: str | None = None
    for index, token in enumerate(argv):
        if token == option and index + 1 < len(argv):
            value = argv[index + 1]
        elif token.startswith(prefix):
            value = token[len(prefix) :]
    return value


def build_early_exit_args(argv: list[str], command: str) -> argparse.Namespace:
    """Build the minimal parsed-args stand-in for a parse-time early-exit event.

    ``parse_args`` raises before returning a namespace for ``--version`` /
    ``--help`` / a usage error, so the telemetry-relevant global flags are
    recovered directly from the raw argument vector: ``--telemetry-debug`` (so the
    would-send JSON still prints under the debug flag) and ``--telemetry-endpoint``
    (so an explicit collector override is still honoured, preserving the prod-safe
    flag precedence). No other flag is read and no free-form value is captured.

    Args:
        argv: The raw argument vector (``sys.argv[1:]`` in production).
        command: The resolved early-exit command label.

    Returns:
        An ``argparse.Namespace`` carrying ``command`` plus any recovered
        telemetry flags.
    """
    namespace = argparse.Namespace(command=command)
    if constants.KANON_TELEMETRY_DEBUG_FLAG in argv:
        namespace.telemetry_debug = True
    endpoint = _argv_option_value(argv, constants.KANON_TELEMETRY_ENDPOINT_FLAG)
    if endpoint is not None:
        namespace.telemetry_endpoint = endpoint
    return namespace


def maybe_emit_early_exit_telemetry(
    argv: list[str],
    exit_code: int,
    *,
    environ: "dict[str, str]",
    now: float | None = None,
    cwd: Path | None = None,
    stream: TextIO | None = None,
    spawn: Callable[..., None] | None = None,
) -> None:
    """Emit a usage event for a parse-time early exit, reusing the main hook.

    Handles the invocations that terminate before subcommand dispatch -- ``kanon
    --version``, ``kanon --help`` / ``-h``, and a bare ``kanon`` (or an argparse
    usage error) -- whose ``SystemExit`` propagates out of ``parse_args`` (or the
    no-subcommand guard) before :func:`maybe_emit_telemetry` would otherwise run.
    The command label is derived from ``argv``, the telemetry flags are recovered
    from ``argv``, the outcome is taken from the early ``SystemExit`` code (a
    non-zero code records a ``SystemExit`` error type and, via
    :func:`build_payload`, an ``error`` status), and the event is dispatched
    through the same silent, non-blocking, never-fail :func:`maybe_emit_telemetry`
    path -- so every skip condition (the opt-out env var, completer subcommands,
    editable/dev installs) is still honoured and nothing is ever written to stderr
    outside debug mode.

    Args:
        argv: The raw argument vector (``sys.argv[1:]`` in production).
        exit_code: The early ``SystemExit`` code (0 for ``--version`` / ``--help``).
        environ: The environment mapping (production passes ``os.environ``).
        now: Current epoch seconds (defaults to ``time.time()``; injectable).
        cwd: The working directory for git provenance (defaults to ``Path.cwd()``).
        stream: The stream for debug output (defaults to ``sys.stderr``).
        spawn: The detached-spawn seam (defaults to ``spawn_detached``).
    """
    command = early_exit_command(argv)
    args = build_early_exit_args(argv, command)
    error_type = None if exit_code == 0 else SystemExit.__name__
    maybe_emit_telemetry(
        args,
        command,
        exit_code=exit_code,
        error_type=error_type,
        duration_ms=0,
        environ=environ,
        now=now,
        cwd=cwd,
        stream=stream,
        spawn=spawn,
    )


def _record_foreground_error(environ: "dict[str, str]") -> None:
    """Append the active foreground telemetry traceback to the error log.

    Best-effort: the emitter must never fail the user's command, so any error
    raised while building or dispatching the event is recorded here (rather than
    silently swallowed) and then suppressed. A failure to write the log itself is
    also suppressed -- there is no channel left to surface it without disturbing
    the foreground command.

    Args:
        environ: The environment mapping (production passes ``os.environ``).
    """
    try:
        log_path = _error_log_path(environ)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as log_fh:
            log_fh.write(traceback.format_exc())
    except OSError:
        return
