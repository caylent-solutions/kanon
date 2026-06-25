"""Manifest XML helpers for the catalog audit remote-url check.

Public API:
    collect_remote_url_findings(target_path, env) -> list[tuple[str, str, str, str]]
        Walk every *-marketplace.xml under target_path/repo-specs/, follow
        <include> chains depth-first, collect every <project remote="X"> and
        resolve "X" to a fetch URL by searching <remote name="X" fetch="...">
        definitions reachable in the same file and its includes.

        Returns a list of (kind, code, message, remediation) tuples:
            R001 -- <remote name="X"> cannot be resolved in the include chain.
            R002 -- Resolved fetch URL uses a non-HTTPS/non-SSH scheme and
                    KANON_ALLOW_INSECURE_REMOTES != "1".
            R003 -- Resolved fetch URL contains a query string ("?") or
                    fragment ("#"); canonicalization is undefined.

    walk_includes_collecting_remotes(xml_path, manifest_repo) -> dict[str, str]
        Depth-first include walker that accumulates <remote name="..."> ->
        fetch="..." mappings from xml_path and all recursively included XML
        files. Used by collect_remote_url_findings.

Spec references:
    spec Section 3.5 soft-spot rule 4 (<remote> definition discoverability).
    spec Section 3.6 (HTTPS-by-default; KANON_ALLOW_INSECURE_REMOTES).
    spec Section 4.8 (--check remote-url).
"""

from __future__ import annotations

import pathlib
import re
import string
from typing import TYPE_CHECKING, NamedTuple, cast

import defusedxml.ElementTree as ET

from kanon_cli.constants import KANON_ALLOW_INSECURE_REMOTES
from kanon_cli.core.metadata import find_catalog_entry_files
from kanon_cli.core.remote_url import RemoteUrlScheme, _classify_remote_url_scheme

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element


XMLParseError = ET.ParseError


class RawFinding(NamedTuple):
    """A raw finding returned by collect_remote_url_findings.

    This avoids a circular import between manifest.py and catalog.py
    (which defines AuditFinding). The catalog._check_remote_url function
    converts RawFinding instances into AuditFinding objects.

    Attributes:
        kind: Severity string -- "error", "warn", or "info".
        code: Machine-readable finding code, e.g. "R001".
        message: Human-readable description of the finding.
        remediation: Suggested action to resolve the finding.
    """

    kind: str
    code: str
    message: str
    remediation: str


def walk_includes_collecting_remotes(
    xml_path: pathlib.Path,
    manifest_repo: pathlib.Path,
) -> dict[str, str]:
    """Depth-first include walker that accumulates <remote> fetch mappings.

    Walks the <include> chain reachable from xml_path, collecting every
    <remote name="..." fetch="..."> definition encountered. The walk is
    cycle-safe and diamond-deduplicated (each file is visited at most once).

    <include name="..."> values are resolved relative to manifest_repo
    (the repo root), matching the repo-tool convention.

    Args:
        xml_path: Absolute path to the root XML file to walk.
        manifest_repo: Absolute path to the root of the manifest repository.
            Include paths are resolved relative to this directory.

    Returns:
        A dict mapping remote name -> fetch URL for every <remote> element
        encountered in xml_path and all transitively included files.
        If a name appears in more than one file, the first-visited definition
        wins (depth-first order).

    Raises:
        xml.etree.ElementTree.ParseError: If any XML file in the chain is
            malformed (caller is responsible for catching this).
        FileNotFoundError: If an <include> references a non-existent file
            (caller is responsible for catching this).
    """
    remotes: dict[str, str] = {}
    visited: set[pathlib.Path] = set()

    def _visit(path: pathlib.Path) -> None:
        canonical = path.resolve()

        if canonical in visited:
            return
        visited.add(canonical)

        tree = ET.parse(str(path))
        root = cast("Element", tree.getroot())

        for remote_el in root.iter("remote"):
            name = remote_el.get("name")
            fetch = remote_el.get("fetch")
            if name and fetch and name not in remotes:
                remotes[name] = fetch

        for include_el in root.iter("include"):
            include_name = include_el.get("name")
            if not include_name:
                continue
            child_path = manifest_repo / include_name
            _visit(child_path)

    _visit(xml_path)
    return remotes


def join_project_repo_url(fetch_url: str, project_name: str) -> str:
    """Join a remote ``fetch`` base URL with a ``<project name>`` repo path.

    A repo-tool manifest declares a ``<remote fetch="...">`` base (typically the
    GITBASE org URL, e.g. ``https://github.com/caylent``) and a
    ``<project name="...">`` whose ``name`` is the repo path beneath that base.
    The actual repository URL a project resolves to is the base joined to the
    project name with a single ``/`` separator.

    This is the single canonical construction for that join; both the live
    ``why`` resolver and the marketplace revision-existence check call it so the
    URL passed to ``git ls-remote`` / ``git clone`` is the same shape (DRY).

    Args:
        fetch_url: The resolved remote ``fetch`` base URL (already expanded).
        project_name: The ``<project name>`` repo path beneath the base.

    Returns:
        ``<fetch_url without trailing slash>/<project_name>``.
    """
    return f"{fetch_url.rstrip('/')}/{project_name}"


_PLACEHOLDER_RE = re.compile(r"\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*")


def _expand_fetch_url(url: str, env: dict[str, str]) -> tuple[str, bool]:
    """Expand ${VAR} placeholders in url using env.

    Uses string.Template.safe_substitute so that variables absent from env are
    left as-is. If the expanded result still contains placeholder patterns, the
    URL is considered unresolved (templated token).

    Args:
        url: The raw fetch URL string, possibly containing ${VAR} tokens.
        env: Environment dict to substitute from.

    Returns:
        A 2-tuple (expanded_url, has_unresolved) where:
        - expanded_url is the URL after applying env substitutions.
        - has_unresolved is True when at least one ${VAR} token could not be
          resolved because its variable was absent from env.
    """
    expanded = string.Template(url).safe_substitute(env)
    has_unresolved = bool(_PLACEHOLDER_RE.search(expanded))
    return expanded, has_unresolved


def _literal_prefix_has_insecure_scheme(url: str) -> bool:
    """Return True when the literal (pre-placeholder) prefix of url has a non-HTTPS/SSH scheme.

    This is used for mixed URLs such as ``http://${HOST}/path`` where the
    scheme is literal and insecure even though the host is a placeholder.
    We extract the portion of url before the first ``${`` or ``$VAR``
    occurrence and classify its scheme.

    Args:
        url: The raw fetch URL string.

    Returns:
        True if the literal prefix carries a non-HTTPS/non-SSH scheme, meaning
        the URL should yield R002 regardless of whether placeholders are resolved.
    """

    match = _PLACEHOLDER_RE.search(url)
    literal_prefix = url[: match.start()] if match else url
    if not literal_prefix:
        return False
    scheme = _classify_remote_url_scheme(literal_prefix)

    return scheme in (RemoteUrlScheme.HTTP, RemoteUrlScheme.FILE)


def collect_remote_url_findings(
    target_path: pathlib.Path,
    env: dict[str, str] | None = None,
) -> list[RawFinding]:
    """Collect remote-url findings for every *-marketplace.xml in target_path.

    For each *-marketplace.xml file under target_path/repo-specs/:
    1. Walk the <include> chain (depth-first, cycle-safe) collecting all
       <remote name="..." fetch="..."> definitions.
    2. For each <project remote="X"> found in the file itself:
       a. If "X" cannot be resolved => R001 ERROR.
       b. If the resolved fetch URL contains "?" or "#" => R003 ERROR.
       c. If the resolved fetch URL uses a non-HTTPS/SSH scheme and
          KANON_ALLOW_INSECURE_REMOTES != "1" => R002 ERROR.

    The env parameter is used instead of os.environ so tests can inject
    KANON_ALLOW_INSECURE_REMOTES without mutating the process environment.

    Args:
        target_path: Root of the manifest repo (must contain repo-specs/).
        env: Environment dict to read KANON_ALLOW_INSECURE_REMOTES from.
            Defaults to {} when None. Uses only this dict -- not os.environ.

    Returns:
        List of RawFinding namedtuples (possibly empty). Callers such as
        catalog._check_remote_url convert these to AuditFinding objects.
    """
    if env is None:
        env = {}

    allow_insecure = env.get(KANON_ALLOW_INSECURE_REMOTES, "") == "1"

    findings: list[RawFinding] = []

    for xml_file in find_catalog_entry_files(target_path):
        try:
            remote_map = walk_includes_collecting_remotes(xml_file, target_path)
        except (XMLParseError, FileNotFoundError, OSError):
            continue

        tree = ET.parse(str(xml_file))
        root = cast("Element", tree.getroot())

        for project_el in root.iter("project"):
            remote_attr = project_el.get("remote")
            if not remote_attr:
                continue

            fetch_url = remote_map.get(remote_attr)

            if fetch_url is None:
                project_name = project_el.get("name", "<unnamed>")
                findings.append(
                    RawFinding(
                        kind="error",
                        code="R001",
                        message=(
                            f"{xml_file}: <project name={project_name!r}> references "
                            f"remote={remote_attr!r} but no <remote name={remote_attr!r}> "
                            "is defined anywhere in the reachable include chain."
                        ),
                        remediation=(
                            f'Add a <remote name="{remote_attr}" fetch="<url>"/> element '
                            "to the manifest or a file reachable via its <include> chain, "
                            "or run 'kanon validate marketplace' to identify structural issues."
                        ),
                    )
                )
                continue

            if "?" in fetch_url or "#" in fetch_url:
                findings.append(
                    RawFinding(
                        kind="error",
                        code="R003",
                        message=(
                            f"{xml_file}: <remote name={remote_attr!r}> has fetch URL "
                            f"{fetch_url!r} which contains a query string or fragment. "
                            "URL canonicalization is undefined for such URLs."
                        ),
                        remediation=(
                            f"Remove the query string or fragment from the fetch URL "
                            f'in <remote name={remote_attr!r} fetch="..."/>.'
                        ),
                    )
                )
                continue

            resolved_url, has_unresolved = _expand_fetch_url(fetch_url, env)

            if has_unresolved and not _literal_prefix_has_insecure_scheme(fetch_url):
                findings.append(
                    RawFinding(
                        kind="info",
                        code="R002-TEMPLATED",
                        message=(
                            f"{xml_file}: <remote name={remote_attr!r}> has fetch URL "
                            f"{fetch_url!r} which contains unresolved variable placeholders. "
                            "The URL scheme cannot be validated until the placeholders are "
                            "substituted at runtime."
                        ),
                        remediation=(
                            f"Ensure all variables referenced in the fetch URL "
                            f"({fetch_url!r}) are set in the environment at audit time, "
                            "or change the URL to a fully-resolved HTTPS or SSH address."
                        ),
                    )
                )
                continue

            url_for_scheme_check = fetch_url if has_unresolved else resolved_url
            scheme = _classify_remote_url_scheme(url_for_scheme_check)
            is_secure = scheme in (
                RemoteUrlScheme.HTTPS,
                RemoteUrlScheme.SSH_GIT_AT,
                RemoteUrlScheme.SSH_PROTOCOL,
            )

            if not is_secure and not allow_insecure:
                findings.append(
                    RawFinding(
                        kind="error",
                        code="R002",
                        message=(
                            f"{xml_file}: <remote name={remote_attr!r}> has fetch URL "
                            f"{fetch_url!r} which uses a non-HTTPS remote URL. "
                            "Only HTTPS and SSH remote URLs are trusted by default "
                            "(spec Section 3.6 HTTPS-by-default policy)."
                        ),
                        remediation=(
                            "Change the fetch URL to use https:// or ssh:// (or git@ shorthand), "
                            "or set KANON_ALLOW_INSECURE_REMOTES=1 to allow insecure remotes "
                            "(intended for tests and local fixtures only)."
                        ),
                    )
                )

    return findings
