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

import os
import pathlib
import re
import string
from typing import TYPE_CHECKING, NamedTuple, cast

import defusedxml.ElementTree as ET

from kanon_cli.constants import KANON_ALLOW_INSECURE_REMOTES
from kanon_cli.core.include_walker import IncludeTree, _walk_includes
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


class ManifestProject(NamedTuple):
    """A project with manifest-wide defaults resolved, retaining checkout identity."""

    name: str
    path: str
    fetch: str
    revision: str
    manifest_path: pathlib.Path


def collect_manifest_projects(xml_path: pathlib.Path, manifest_repo: pathlib.Path) -> list[ManifestProject]:
    """Resolve projects across the validated include graph without Git or network.

    Includes are rooted at the manifest repository, cycle-checked and diamond-
    deduplicated by the shared walker. Remotes and the default apply globally,
    including when defined in another included file. Projects, removals and
    extensions follow declaration order after expanding includes. Nested project
    names and checkout paths follow their parent; include revisions apply only
    to the included file's top-level projects. Unresolved remotes remain a
    validation concern and are omitted from the explanatory graph.
    """
    include_tree = _walk_includes(xml_path, manifest_repo)
    declarations: list[tuple[pathlib.Path, Element, str]] = []

    def visit(node: IncludeTree, include_revision: str = "") -> None:
        path = manifest_repo / node.path
        root = cast("Element", ET.parse(str(path)).getroot())
        children = {(manifest_repo / child.path).resolve(): child for child in node.includes}
        for element in root:
            if element.tag == "include":
                child = children.pop((manifest_repo / element.get("name", "")).resolve(), None)
                if child is not None:
                    visit(child, element.get("revision", ""))
            else:
                declarations.append((path, element, include_revision))

    visit(include_tree)
    remotes: dict[str, tuple[str, str]] = {}
    default: tuple[str, str] | None = None
    for _path, element, _include_revision in declarations:
        if element.tag == "remote":
            name, fetch = element.get("name", ""), element.get("fetch", "")
            if name and fetch:
                declaration = (fetch, element.get("revision", ""))
                if name in remotes and remotes[name] != declaration:
                    raise ValueError(f"Conflicting manifest remote {name!r}")
                remotes[name] = declaration
        elif element.tag == "default":
            if not element.attrib:
                continue
            declaration = (element.get("remote", ""), element.get("revision", ""))
            if default is not None and default != declaration:
                raise ValueError("Conflicting manifest default remote or revision")
            default = declaration

    default_remote, default_revision = default or ("", "")
    projects: list[ManifestProject] = []

    def add_project(
        element: Element, path: pathlib.Path, include_revision: str = "", parent: ManifestProject | None = None
    ) -> None:
        name = element.get("name", "")
        remote = remotes.get(element.get("remote") or default_remote)
        if not name or remote is None:
            return
        if parent is not None:
            name = os.path.join(parent.name, name)
        checkout_path = (element.get("path", "") or name).rstrip("/")
        if parent is not None:
            checkout_path = os.path.join(parent.path, checkout_path)
        fetch, remote_revision = remote
        revision = element.get("revision", include_revision) or remote_revision or default_revision
        project = ManifestProject(name, checkout_path, fetch, revision, path)
        if not any((p.name, p.path) == (name, checkout_path) for p in projects):
            projects.append(project)
        for child in element.findall("project"):
            add_project(child, path, parent=project)

    for path, element, include_revision in declarations:
        if element.tag == "project":
            add_project(element, path, include_revision)
        elif element.tag in ("remove-project", "extend-project"):
            name, checkout_path = element.get("name", ""), element.get("path", "")
            if not name and (element.tag == "extend-project" or not checkout_path):
                raise ValueError(f"Manifest {element.tag} requires a project name or path")
            matching = [
                p for p in projects if (not name or p.name == name) and (not checkout_path or p.path == checkout_path)
            ]
            base_revision = element.get("base-rev", "")
            checks_revision = element.tag == "remove-project" or bool(element.get("revision"))
            if base_revision and checks_revision and any(p.revision != base_revision for p in matching):
                raise ValueError(f"Manifest {element.tag} base-rev does not match project {name or checkout_path!r}")
            if element.tag == "remove-project":
                projects = [p for p in projects if p not in matching]
                continue
            destination = element.get("dest-path", "")
            if destination and not checkout_path and len(matching) > 1:
                raise ValueError(f"Manifest extend-project dest-path matches multiple projects: {name!r}")
            remote_name = element.get("remote", "")
            remote = remotes.get(remote_name) if remote_name else None
            updated: list[ManifestProject] = []
            for project in projects:
                if project in matching:
                    if remote_name and remote is None:
                        continue
                    project = project._replace(
                        path=destination.rstrip("/") or project.path,
                        fetch=remote[0] if remote is not None else project.fetch,
                        revision=element.get("revision") or project.revision,
                    )
                updated.append(project)
            projects = updated
    return projects


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
