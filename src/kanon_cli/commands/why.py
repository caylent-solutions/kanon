"""kanon why subcommand: explain why a project is in the resolved dependency tree.

Reads the .kanon file, resolves the full dependency tree (from .kanon.lock when
present; otherwise live-resolves against the catalog), locates all chains ending
at the requested node, and prints one chain per line.

Chain format (text mode):
  <top-source> -> <include-path>@<sha> -> ... -> <project>@<sha>

Argument matching (spec Section 4.5 step 2):
  All three categories are evaluated before deciding. No early-exit on first hit.
  (a) <project> repo URL -- canonicalized via canonicalize_repo_url. Match against
      every <project> node's canonicalized URL.
  (b) Transitive XML manifest path -- exact-string equality against every <include>
      node's path_in_repo (ref) value.
  (c) Top-level source name -- normalized via derive_source_name so that case and
      dash/underscore differences are treated as equivalent.

Ambiguity (spec Section 4.5 step 3):
  If two or more categories match, a hard error is raised naming every interpretation
  so the operator knows how to disambiguate.

Spec reference: spec/kanon-list-add-lock-features-spec.md Section 4.5
behaviour steps 1-3, 5 (text format). Section 7 for KANON_WHY_FORMAT.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

import defusedxml.ElementTree as ET

from kanon_cli.repo.subcmds.envsubst import _UNRESOLVED_PATTERN
from kanon_cli.constants import (
    KANON_ALLOW_INSECURE_REMOTES,
    KANON_KANON_FILE_DEFAULT,
    KANON_KANON_FILE_ENV,
    KANON_LOCK_FILE,
    KANON_WHY_FORMAT,
    KANON_WHY_FORMAT_DEFAULT,
    KANON_WHY_FORMAT_JSON,
    KANON_WHY_JSON_INDENT,
    KANON_WHY_SUGGEST_MAX_DISTANCE,
    KANON_WHY_SUGGEST_TOP_N,
    MISSING_CATALOG_ERROR_TEMPLATE,
    WHY_SCOPE_TOP_LEVEL,
    WHY_SCOPE_TRANSITIVE,
)
from kanon_cli.utils.levenshtein import levenshtein_distance
from kanon_cli.core.cli_args import add_catalog_source_arg
from kanon_cli.core.include_walker import IncludeTree, _walk_includes
from kanon_cli.core.install import _resolve_ref_to_sha
from kanon_cli.core.kanonenv import parse_kanonenv
from kanon_cli.core.lockfile import Lockfile, IncludeEntry, read_lockfile
from kanon_cli.core.manifest import walk_includes_collecting_remotes
from kanon_cli.core.metadata import derive_source_name
from kanon_cli.core.remote_url import _enforce_remote_url_policy
from kanon_cli.core.url import canonicalize_repo_url
from kanon_cli.utils.lock_file_path import derive_lock_file_path


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ChainNode:
    """A single node in a resolved dependency chain.

    Attributes:
        kind: One of 'source', 'include', or 'project'.
        name: Human-readable name of the node.
        ref: For 'include' nodes, the path_in_repo value (e.g. 'repo-specs/bar.xml').
            For 'source' and 'project' nodes this is None.
        sha: The resolved git commit SHA for this node.
        url: The repository URL for 'source' and 'project' nodes. None for 'include' nodes.
        canonical_url: The canonicalized URL for 'project' nodes (used for URL matching).
            None for 'source' and 'include' nodes.
        scope: Scope tag for the node. For nodes built from the lockfile, source nodes
            carry WHY_SCOPE_TOP_LEVEL and include nodes carry WHY_SCOPE_TRANSITIVE.
            None for nodes built via live-resolve or for project nodes.
        children: Direct child nodes (populated when building the tree from the lockfile).
    """

    kind: str
    name: str
    ref: str | None
    sha: str
    url: str | None
    canonical_url: str | None = None
    scope: str | None = None
    children: list[ChainNode] = field(default_factory=list)


@dataclass
class ResolvedTree:
    """The complete resolved dependency tree.

    Attributes:
        sources: One ChainNode per top-level KANON_SOURCE_* entry.
            Each source's children are include nodes and project nodes.
    """

    sources: list[ChainNode]


# ---------------------------------------------------------------------------
# Lockfile-to-tree conversion
# ---------------------------------------------------------------------------


def _include_entry_to_node(entry: IncludeEntry) -> ChainNode:
    """Convert a lockfile IncludeEntry to a ChainNode (recursively).

    Each include node is tagged with WHY_SCOPE_TRANSITIVE to distinguish it
    from top-level source nodes (tagged WHY_SCOPE_TOP_LEVEL) when walking
    chains from a named node.

    Args:
        entry: A lockfile IncludeEntry dataclass instance.

    Returns:
        A ChainNode of kind 'include' with nested child nodes.
    """
    node = ChainNode(
        kind="include",
        name=entry.name,
        ref=entry.path_in_repo,
        sha=entry.resolved_sha,
        url=None,
        scope=WHY_SCOPE_TRANSITIVE,
    )
    for child_include in entry.includes:
        node.children.append(_include_entry_to_node(child_include))
    return node


def _collect_leaf_include_nodes(include_nodes: list[ChainNode]) -> list[ChainNode]:
    """Collect the leaf include nodes (those with no nested include children).

    A leaf include node is an include node that has no include-kind children.
    Project nodes added as children are ignored when checking for leaf status --
    this function is called before projects are attached.

    Args:
        include_nodes: The include ChainNode instances to search recursively.

    Returns:
        A flat list of leaf include ChainNode objects in DFS pre-order.
    """
    leaves: list[ChainNode] = []
    for node in include_nodes:
        nested_includes = [c for c in node.children if c.kind == "include"]
        if not nested_includes:
            leaves.append(node)
        else:
            leaves.extend(_collect_leaf_include_nodes(nested_includes))
    return leaves


def _build_tree_from_lockfile(lockfile: Lockfile) -> ResolvedTree:
    """Build a ResolvedTree from a parsed Lockfile dataclass.

    The tree mirrors the lockfile structure:
      - One ChainNode(kind='source') per [[sources]] entry.
      - Each source's children: ChainNode(kind='include') nodes (recursive).
      - Project nodes are placed under the leaf include nodes (the deepest
        include in each branch). When a source has no includes, projects are
        placed directly under the source.

    The lockfile v1 schema stores projects flat under the source rather than
    under their declaring include. To reconstruct include-node segments in
    chain output (e.g. ``FOO -> repo-specs/bar.xml@<sha> -> baz@<sha>``),
    this function places all source-level projects under every leaf include
    node (match by include position). When no includes are present the
    projects remain direct children of the source node.

    Args:
        lockfile: A fully parsed Lockfile dataclass instance.

    Returns:
        A ResolvedTree with one source node per lockfile source entry.
    """
    sources: list[ChainNode] = []

    for source_entry in lockfile.sources:
        source_node = ChainNode(
            kind="source",
            name=source_entry.name,
            ref=None,
            sha=source_entry.resolved_sha,
            url=source_entry.url,
            scope=WHY_SCOPE_TOP_LEVEL,
        )

        # Build include subtree (recursive)
        include_chain_roots: list[ChainNode] = []
        for inc in source_entry.includes:
            include_chain_roots.append(_include_entry_to_node(inc))

        # Build project leaf nodes
        project_nodes: list[ChainNode] = [
            ChainNode(
                kind="project",
                name=proj.name,
                ref=None,
                sha=proj.resolved_sha,
                url=proj.url,
                canonical_url=proj.canonical_url,
            )
            for proj in source_entry.projects
        ]

        if include_chain_roots:
            # Attach includes as direct children of the source
            for inc_node in include_chain_roots:
                source_node.children.append(inc_node)

            # Place project nodes under every leaf include so the chain output
            # contains the intermediate include segment:
            #   <source> -> <include-path>@<sha> -> <project>@<sha>
            leaf_includes = _collect_leaf_include_nodes(include_chain_roots)
            for leaf in leaf_includes:
                for proj_node in project_nodes:
                    # Each leaf gets its own ChainNode instance to avoid sharing
                    leaf.children.append(
                        ChainNode(
                            kind="project",
                            name=proj_node.name,
                            ref=proj_node.ref,
                            sha=proj_node.sha,
                            url=proj_node.url,
                            canonical_url=proj_node.canonical_url,
                        )
                    )
        else:
            # No includes: projects are direct children of the source node
            for proj_node in project_nodes:
                source_node.children.append(proj_node)

        sources.append(source_node)

    return ResolvedTree(sources=sources)


# ---------------------------------------------------------------------------
# Live tree resolution
# ---------------------------------------------------------------------------


class LiveResolveError(Exception):
    """Raised when the live-resolve catalog walk fails for a named source.

    Attributes:
        name: The source or project name that could not be resolved.
        reason: A human-readable explanation of the failure (one line).
    """

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"ERROR: cannot resolve '{self.name}' via catalog walk: {self.reason}\n"
            "Remediation: Verify --catalog-source URL + revision are reachable "
            "and the catalog manifest is well-formed."
        )


def _include_tree_to_chain_nodes(
    include_tree: IncludeTree,
    source_sha: str,
    source_url: str,
) -> list[ChainNode]:
    """Convert an ``IncludeTree`` to a flat list of include ``ChainNode`` roots.

    Each node in the tree becomes an ``include`` ChainNode. Children are attached
    recursively so the resulting nodes mirror the ``_build_tree_from_lockfile``
    structure.  The ``sha`` of each include node is set to ``source_sha`` because
    the live-resolve path does not have per-include commit SHAs (those require a
    full ``repo sync``).

    Only the direct children of the root ``IncludeTree`` node are returned (the
    root itself represents the manifest XML entry point, not an include).

    Args:
        include_tree: Root ``IncludeTree`` from ``_walk_includes``.
        source_sha: The resolved SHA of the owning source, used as a
            placeholder SHA for all include nodes on the live-resolve path.
        source_url: The URL of the source repo, stored on each include node.

    Returns:
        A list of ``ChainNode(kind='include')`` objects representing the
        direct include children of the manifest root, with nested children
        attached recursively.
    """

    def _convert(node: IncludeTree) -> ChainNode:
        inc_node = ChainNode(
            kind="include",
            name=str(node.path),
            ref=str(node.path),
            sha=source_sha,
            url=None,
        )
        for child in node.includes:
            inc_node.children.append(_convert(child))
        return inc_node

    return [_convert(child) for child in include_tree.includes]


def _substitute_fetch_url(
    fetch_url: str,
    globals_map: dict[str, str],
    source_name: str,
    kanon_file: pathlib.Path,
) -> str:
    """Substitute ``${VAR}`` placeholders in a remote ``fetch`` URL.

    Applies the ``.kanon`` globals to any ``${VAR}`` placeholder in
    ``fetch_url`` using ``os.path.expandvars`` -- the same primitive
    ``repo envsubst`` / ``envsubst.py::resolve_variable`` uses.  Variables are
    set into a copy of the process environment for the duration of the call and
    then immediately restored, so the substitution does not mutate the global
    process state.

    If any ``${VAR}`` placeholder survives after substitution (i.e. the
    variable was not declared in the ``.kanon`` globals), the function
    raises ``LiveResolveError`` with an actionable message naming the missing
    variable and the ``.kanon`` file path.

    A ``fetch_url`` with no ``${...}`` patterns is returned unchanged without
    touching ``os.environ``.

    Args:
        fetch_url: The raw remote ``fetch`` attribute value from the manifest
            XML (may contain ``${VAR}`` placeholders).
        globals_map: The ``.kanon`` globals dict from ``parse_kanonenv``
            (``kanonenv["globals"]``).
        source_name: The KANON_SOURCE name, used in error messages.
        kanon_file: Path to the ``.kanon`` file, used in error messages.

    Returns:
        The ``fetch_url`` with all ``${VAR}`` placeholders replaced by their
        values from ``globals_map``.

    Raises:
        LiveResolveError: If a ``${VAR}`` placeholder has no matching global
            in ``globals_map``, naming the missing variable and ``.kanon`` path.
    """
    if "${" not in fetch_url:
        return fetch_url

    # Temporarily inject globals into os.environ so os.path.expandvars resolves
    # ${VAR} patterns.  Save and restore any keys we overwrite so the process
    # environment is unchanged after this call.
    overwritten: dict[str, str | None] = {}
    for key, value in globals_map.items():
        overwritten[key] = os.environ.get(key)
        os.environ[key] = value

    try:
        substituted = os.path.expandvars(fetch_url)
    finally:
        for key, original in overwritten.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original

    unresolved = _UNRESOLVED_PATTERN.findall(substituted)
    if unresolved:
        missing_var = unresolved[0]
        raise LiveResolveError(
            source_name,
            f"remote fetch URL {fetch_url!r} references ${{{missing_var}}} "
            f"but {missing_var!r} is not declared in {kanon_file}. "
            f"Add {missing_var}=<value> to {kanon_file} or use a concrete fetch URL.",
        )

    return substituted


def _build_project_nodes_from_xml(
    manifest_xml_path: pathlib.Path,
    manifest_repo: pathlib.Path,
    source_sha: str,
    source_name: str,
    globals_map: dict[str, str] | None = None,
    kanon_file: pathlib.Path | None = None,
) -> list[ChainNode]:
    """Parse ``<project>`` elements from a manifest XML and return project ``ChainNode`` objects.

    Resolves the project URL by looking up each project's ``remote`` attribute
    in the remote-name -> fetch-URL mapping collected by
    ``walk_includes_collecting_remotes``.  Remote ``fetch`` values that contain
    ``${VAR}`` placeholders are substituted from ``globals_map`` via
    ``_substitute_fetch_url`` before canonicalization.  Only ``<project>``
    elements whose remote resolves to a concrete, canonicalizable fetch URL are
    included; remotes with no entry in the remote map are skipped (they produce
    R001 audit findings -- a separate validation concern).

    The ``sha`` of each project node is set to ``source_sha`` because the
    live-resolve path does not run ``repo sync`` and therefore has no
    per-project commit SHAs.

    Args:
        manifest_xml_path: Absolute path to the root manifest XML file.
        manifest_repo: Absolute path to the root of the manifest repository.
        source_sha: The resolved SHA of the owning source, used as a
            placeholder SHA for all project nodes on the live-resolve path.
        source_name: The KANON_SOURCE_<name> key, used for error context.
        globals_map: The ``.kanon`` globals dict from ``parse_kanonenv``
            (``kanonenv["globals"]``).  When supplied, ``${VAR}`` placeholders
            in remote ``fetch`` URLs are resolved from this map.  Omit (or pass
            ``None``) to skip placeholder substitution (legacy / non-live-resolve
            callers).
        kanon_file: Path to the ``.kanon`` file, forwarded to
            ``_substitute_fetch_url`` for actionable error messages.  Required
            when ``globals_map`` is supplied.

    Returns:
        A list of ``ChainNode(kind='project')`` objects, one per resolvable
        ``<project>`` element found in the manifest and its reachable includes.

    Raises:
        LiveResolveError: If the manifest XML cannot be parsed, or if a
            ``${VAR}`` placeholder in a remote ``fetch`` has no matching global.
    """
    resolved_globals: dict[str, str] = globals_map if globals_map is not None else {}
    resolved_kanon_file: pathlib.Path = kanon_file if kanon_file is not None else pathlib.Path(".kanon")

    try:
        remote_map = walk_includes_collecting_remotes(manifest_xml_path, manifest_repo)
        tree = ET.parse(str(manifest_xml_path))
        root = tree.getroot()
    except Exception as exc:
        raise LiveResolveError(
            source_name,
            f"failed to parse manifest XML at {manifest_xml_path}: {exc}",
        ) from exc

    if root is None:
        return []

    project_nodes: list[ChainNode] = []
    for project_el in root.iter("project"):
        remote_attr = project_el.get("remote")
        project_name = project_el.get("name", "")
        if not remote_attr or not project_name:
            # Skip projects with no remote attribute or empty name -- these
            # cannot be resolved to a canonical URL without a <default> lookup.
            continue

        raw_fetch = remote_map.get(remote_attr)
        if raw_fetch is None:
            # Remote is unresolvable; skip rather than hard-fail so that
            # valid projects in the same manifest still produce chain nodes.
            # The audit command (kanon catalog audit) surfaces R001 for these.
            continue

        # Substitute ${VAR} placeholders (e.g. ${GITBASE}) from .kanon globals
        # before canonicalization.  Fails fast when a placeholder has no match.
        fetch_url = _substitute_fetch_url(
            raw_fetch,
            resolved_globals,
            source_name,
            resolved_kanon_file,
        )

        raw_url = f"{fetch_url.rstrip('/')}/{project_name}"
        try:
            canonical = canonicalize_repo_url(raw_url)
        except ValueError:
            # URL is genuinely unresolvable after substitution (e.g. non-URL
            # value in fetch that is not a ${VAR} placeholder); skip.
            continue

        project_nodes.append(
            ChainNode(
                kind="project",
                name=project_name,
                ref=None,
                sha=source_sha,
                url=raw_url,
                canonical_url=canonical,
            )
        )

    return project_nodes


def _clone_source_repo(
    url: str,
    revision: str,
    source_name: str,
    dest: pathlib.Path,
) -> None:
    """Clone a source repo at a specific revision into ``dest``.

    Uses ``git clone --depth 1 --branch <revision>`` with the last path
    component of ``revision`` stripped of the ``refs/tags/`` or
    ``refs/heads/`` prefix so that git receives a plain branch-or-tag name.

    Args:
        url: The git remote URL of the source repo.
        revision: The revision spec string from the .kanon file (e.g.
            ``"refs/tags/1.0.0"`` or ``"main"``).
        source_name: The source name, used only in ``LiveResolveError`` messages.
        dest: The directory to clone into.

    Raises:
        LiveResolveError: If ``git clone`` exits non-zero.
    """
    # Strip canonical ref prefixes so git receives a plain name.
    branch_or_tag = revision
    for prefix in ("refs/tags/", "refs/heads/"):
        if revision.startswith(prefix):
            branch_or_tag = revision[len(prefix) :]
            break

    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", branch_or_tag, url, str(dest)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise LiveResolveError(
            source_name,
            f"git clone failed for {url}@{revision}: {result.stderr.strip()}",
        )


def _populate_source_children_from_manifest(
    source_node: ChainNode,
    source_url: str,
    revision: str,
    manifest_path: str,
    source_sha: str,
    source_name: str,
    tmp_base: pathlib.Path,
    globals_map: dict[str, str] | None = None,
    kanon_file: pathlib.Path | None = None,
) -> None:
    """Clone the source repo and attach include/project children to ``source_node``.

    Clones the source repo at the stored revision, walks the manifest XML at
    ``manifest_path`` for ``<include>`` chains and ``<project>`` elements, and
    appends the resulting ``ChainNode`` children to ``source_node``.

    This mirrors the lockfile-path child-building logic in
    ``_build_tree_from_lockfile`` (~215-240) so that ``_match_by_url`` and
    ``_match_by_xml_path`` find real nodes in the live-resolve tree.

    Args:
        source_node: The ``ChainNode(kind='source')`` to attach children to.
        source_url: The git URL of the source (manifest) repo.
        revision: The revision spec from the .kanon file.
        manifest_path: Repo-relative path to the manifest XML (e.g.
            ``"repo-specs/foo-marketplace.xml"``).
        source_sha: The resolved SHA of this source, used as placeholder SHA
            for include and project nodes on the live-resolve path.
        source_name: The KANON_SOURCE_<name> key, used in error messages.
        tmp_base: A temporary directory path under which the clone is placed.
        globals_map: The ``.kanon`` globals dict from ``parse_kanonenv``
            (``kanonenv["globals"]``).  Forwarded to ``_build_project_nodes_from_xml``
            so that ``${VAR}`` placeholders in remote ``fetch`` URLs are
            resolved.  Pass ``None`` to skip placeholder substitution.
        kanon_file: Path to the ``.kanon`` file forwarded for error messages.

    Raises:
        LiveResolveError: If cloning fails or if the manifest XML cannot be
            parsed, or if a ``${VAR}`` placeholder has no matching global.
    """
    clone_dest = tmp_base / source_name
    _clone_source_repo(
        url=source_url,
        revision=revision,
        source_name=source_name,
        dest=clone_dest,
    )

    manifest_xml_path = clone_dest / manifest_path
    if not manifest_xml_path.exists():
        raise LiveResolveError(
            source_name,
            f"manifest XML not found in cloned repo at path {manifest_path!r}. "
            "Verify KANON_SOURCE_{name}_PATH is correct.",
        )

    try:
        include_tree = _walk_includes(manifest_xml_path, clone_dest)
    except Exception as exc:
        raise LiveResolveError(
            source_name,
            f"failed to walk <include> chain in {manifest_path}: {exc}",
        ) from exc

    include_roots = _include_tree_to_chain_nodes(include_tree, source_sha, source_url)
    project_nodes = _build_project_nodes_from_xml(
        manifest_xml_path,
        clone_dest,
        source_sha,
        source_name,
        globals_map=globals_map,
        kanon_file=kanon_file,
    )

    # Attach children mirroring _build_tree_from_lockfile (~215-240):
    # includes as direct children of the source; projects under every leaf
    # include, or directly under the source when no includes are present.
    if include_roots:
        for inc_node in include_roots:
            source_node.children.append(inc_node)
        leaf_includes = _collect_leaf_include_nodes(include_roots)
        for leaf in leaf_includes:
            for proj_node in project_nodes:
                leaf.children.append(
                    ChainNode(
                        kind="project",
                        name=proj_node.name,
                        ref=proj_node.ref,
                        sha=proj_node.sha,
                        url=proj_node.url,
                        canonical_url=proj_node.canonical_url,
                    )
                )
    else:
        for proj_node in project_nodes:
            source_node.children.append(proj_node)


def _live_resolve_tree(kanon_file: pathlib.Path, catalog_source: str) -> ResolvedTree:
    """Resolve the dependency tree live from the .kanon file.

    This path is used when no .kanon.lock is present. Requires a catalog source
    to satisfy the caller's precondition check; the actual source resolution
    reads URLs and revisions directly from the parsed .kanon file entries.

    For each KANON_SOURCE_<name> entry in the .kanon file:
      - Enforces the remote URL security policy.
      - Resolves the declared revision to a concrete commit SHA via git ls-remote.
      - Builds a ChainNode(kind='source') for the source.
      - Clones the source repo and walks its manifest XML to populate the
        source node's project and include children, mirroring the tree
        structure built by _build_tree_from_lockfile (~215-240) for the
        lockfile path. This makes _match_by_url and _match_by_xml_path
        traverse real nodes on the live-resolve path.

    Args:
        kanon_file: Path to the .kanon configuration file.
        catalog_source: The catalog source string in '<git-url>@<ref>' format.
            Not used for resolution -- included as a parameter to preserve the
            caller's precondition API (catalog source required on live path).

    Returns:
        A ResolvedTree with one source ChainNode per .kanon source entry,
        each with its include and project children populated.

    Raises:
        LiveResolveError: If ref-to-SHA resolution fails for any source entry,
            if the remote URL policy rejects a source URL, if git clone fails,
            or if the manifest XML cannot be parsed.
        ValueError: From parse_kanonenv when the .kanon file is malformed or
            missing required source variables.
    """
    if not catalog_source:
        raise ValueError(
            "catalog_source must be a non-empty '<git-url>@<ref>' string; "
            "received an empty value. "
            "The caller must verify --catalog-source is present before invoking _live_resolve_tree."
        )
    allow_insecure: bool = os.environ.get(KANON_ALLOW_INSECURE_REMOTES) == "1"
    kanonenv = parse_kanonenv(kanon_file)
    globals_map: dict[str, str] = kanonenv.get("globals", {})
    source_nodes: list[ChainNode] = []

    with tempfile.TemporaryDirectory(prefix="kanon-why-live-") as _tmp_dir:
        tmp_base = pathlib.Path(_tmp_dir)

        for source_name in kanonenv["KANON_SOURCES"]:
            source_data = kanonenv["sources"][source_name]
            url: str = source_data["url"]
            revision: str = source_data["revision"]
            manifest_path: str = source_data["path"]

            try:
                _enforce_remote_url_policy(
                    url=url,
                    allow_insecure=allow_insecure,
                    remote_name=source_name,
                    source_path=source_name,
                )
            except Exception as exc:
                raise LiveResolveError(source_name, str(exc)) from exc

            try:
                ref_resolution = _resolve_ref_to_sha(url, revision)
            except ValueError as exc:
                raise LiveResolveError(source_name, str(exc)) from exc

            source_node = ChainNode(
                kind="source",
                name=source_name,
                ref=manifest_path,
                sha=ref_resolution.sha,
                url=url,
            )

            _populate_source_children_from_manifest(
                source_node=source_node,
                source_url=url,
                revision=revision,
                manifest_path=manifest_path,
                source_sha=ref_resolution.sha,
                source_name=source_name,
                tmp_base=tmp_base,
                globals_map=globals_map,
                kanon_file=kanon_file,
            )

            source_nodes.append(source_node)

    return ResolvedTree(sources=source_nodes)


# ---------------------------------------------------------------------------
# Chain walking (DFS)
# ---------------------------------------------------------------------------


def _walk_chains(tree: ResolvedTree, target_canonical_url: str) -> list[list[ChainNode]]:
    """Walk the resolved tree depth-first and collect all chains ending at the target.

    A chain is a list of ChainNode objects from a top-level source node down to
    the target project node (inclusive).

    Args:
        tree: The fully resolved dependency tree.
        target_canonical_url: The canonical URL of the project node to find.

    Returns:
        A list of chains. Each chain is a list of ChainNode objects.
        Returns an empty list when no chain reaches the target.
    """
    found_chains: list[list[ChainNode]] = []

    def _dfs(node: ChainNode, path: list[ChainNode]) -> None:
        current_path = path + [node]

        # Check if this node is the target project
        if node.kind == "project" and node.canonical_url == target_canonical_url:
            found_chains.append(current_path)
            return

        # Recurse into children
        for child in node.children:
            _dfs(child, current_path)

    for source_node in tree.sources:
        _dfs(source_node, [])

    return found_chains


def _walk_chains_from_node(tree: ResolvedTree, target_node: ChainNode) -> list[list[ChainNode]]:
    """Walk the resolved tree DFS and collect all chains passing through the target node.

    Used when the argument matched an include or source node (not a project URL).

    Scope-aware chain construction:
      - When target_node carries WHY_SCOPE_TOP_LEVEL (a lockfile top-level source),
        return a single-node chain containing just that source. The source is the
        terminal point of interest; callers requested the source by name and the
        single-node chain correctly represents "this source is installed directly".
      - When target_node carries WHY_SCOPE_TRANSITIVE (a lockfile transitive include),
        walk all descendant chains from the include node down to leaf project nodes,
        prefixed by the path from the tree root to the include (existing behaviour).
      - When target_node.scope is None (live-resolve source or project node), fall
        back to the original leaf-collection behaviour: descend all children or
        return the node itself when it has no children.

    Args:
        tree: The fully resolved dependency tree.
        target_node: The ChainNode (source or include kind) to find and report chains for.

    Returns:
        A list of chains. Each chain is a list of ChainNode objects starting from
        a top-level source down through target_node and its descendants.
        When target_node carries WHY_SCOPE_TOP_LEVEL, returns a single-element list
        containing the single-node chain [target_node].
        When target_node carries WHY_SCOPE_TRANSITIVE, returns all chains passing
        through it down to leaf project nodes.
        Returns an empty list when no chains pass through the target node.
    """
    found_chains: list[list[ChainNode]] = []

    def _dfs_collect_all_leaves(node: ChainNode, path: list[ChainNode]) -> None:
        """Collect all chains from the current node to every leaf descendant.

        A leaf is either:
          - A 'project' node (always a leaf regardless of children), or
          - Any node with no children (source or include with no nested entries).
        """
        current_path = path + [node]
        if node.kind == "project":
            found_chains.append(current_path)
            return
        if not node.children:
            # Source or include node with no nested children: the node itself
            # is the leaf of the chain (e.g. a live-resolved source with no
            # projects, or a top-level source that is the match target).
            found_chains.append(current_path)
            return
        for child in node.children:
            _dfs_collect_all_leaves(child, current_path)

    def _dfs_find(node: ChainNode, path: list[ChainNode]) -> None:
        """Walk the tree looking for target_node; once found, collect chains."""
        if node is target_node:
            if node.scope == WHY_SCOPE_TOP_LEVEL:
                # Top-level source match: return a single-node chain. The source is
                # the terminal point; no need to descend into includes or projects.
                found_chains.append([node])
                return
            # Transitive include or unscoped (live-resolve) node: collect all leaves.
            _dfs_collect_all_leaves(node, path)
            return
        for child in node.children:
            _dfs_find(child, path + [node])

    for source_node in tree.sources:
        _dfs_find(source_node, [])

    return found_chains


# ---------------------------------------------------------------------------
# Three-category argument matchers
# ---------------------------------------------------------------------------


def _match_by_url(tree: ResolvedTree, argument: str) -> list[ChainNode]:
    """Match the argument against project and source nodes by canonicalized URL.

    Attempts to canonicalize the argument. If canonicalization fails (argument is
    not a valid URL), returns an empty list -- no match in this category.

    Matches:
    - ``project`` nodes: ``node.canonical_url == canonicalize_repo_url(argument)``.
    - ``source`` nodes: ``canonicalize_repo_url(node.url) == target_canonical``
      when the source carries a URL (live-resolve path sets ``source.url`` to the
      git remote URL of the manifest repo).

    Args:
        tree: The fully resolved dependency tree.
        argument: The raw argument string from the CLI.

    Returns:
        List of ChainNode objects (project or source) whose canonical URL equals
        ``canonicalize_repo_url(argument)``.  Empty when no match or when
        canonicalization raises ValueError.
    """
    try:
        target_canonical = canonicalize_repo_url(argument)
    except ValueError:
        return []

    matches: list[ChainNode] = []

    # Check top-level source nodes by their URL.
    for source_node in tree.sources:
        if source_node.url is not None:
            try:
                source_canonical = canonicalize_repo_url(source_node.url)
            except ValueError:
                source_canonical = None
            if source_canonical == target_canonical:
                matches.append(source_node)

    def _collect_projects(node: ChainNode) -> None:
        if node.kind == "project" and node.canonical_url == target_canonical:
            matches.append(node)
        for child in node.children:
            _collect_projects(child)

    for source_node in tree.sources:
        _collect_projects(source_node)

    return matches


def _match_by_xml_path(tree: ResolvedTree, argument: str) -> list[ChainNode]:
    """Match the argument against include and source nodes by XML path equality.

    Matches:
    - ``include`` nodes: ``node.ref == argument`` (the ``path_in_repo`` value).
    - ``source`` nodes: ``node.ref == argument`` when the source carries a root
      manifest path in ``ref`` (set on the live-resolve path to
      ``KANON_SOURCE_<name>_PATH``).

    Args:
        tree: The fully resolved dependency tree.
        argument: The raw argument string from the CLI.

    Returns:
        List of ChainNode objects (include or source) whose ``ref`` exactly equals
        the argument.  Empty when no match.
    """
    matches: list[ChainNode] = []

    # Check top-level source nodes by their root manifest path (ref).
    for source_node in tree.sources:
        if source_node.ref is not None and source_node.ref == argument:
            matches.append(source_node)

    def _collect_includes(node: ChainNode) -> None:
        if node.kind == "include" and node.ref == argument:
            matches.append(node)
        for child in node.children:
            _collect_includes(child)

    for source_node in tree.sources:
        _collect_includes(source_node)

    return matches


def _match_by_source_name(tree: ResolvedTree, argument: str) -> list[ChainNode]:
    """Match the argument against top-level source nodes via derive_source_name normalization.

    The argument and each source node's name are both normalized with
    derive_source_name before comparison, so case differences and dash/underscore
    differences are ignored.

    Args:
        tree: The fully resolved dependency tree.
        argument: The raw argument string from the CLI.

    Returns:
        List of source ChainNode objects whose normalized name equals the normalized
        argument. Empty when no match.
    """
    normalized_arg = derive_source_name(argument)
    return [source for source in tree.sources if derive_source_name(source.name) == normalized_arg]


# ---------------------------------------------------------------------------
# Ambiguity-aware match resolution
# ---------------------------------------------------------------------------


@dataclass
class _MatchHit:
    """A single match result from one of the three matching categories.

    Attributes:
        category: One of 'url', 'xml_path', 'source_name'.
        label: Human-readable description of the matched value for the error message.
        node: The matched ChainNode.
    """

    category: str
    label: str
    node: ChainNode


def _resolve_match(tree: ResolvedTree, argument: str) -> _MatchHit:
    """Evaluate all three matching categories and return the single unambiguous hit.

    All three categories (URL, XML path, source name) are evaluated. The strategy
    is NOT stop-at-first-match -- every category is checked regardless of prior hits.

    When zero matches are found, the not-found error message includes a closest-match
    suggestion list (up to KANON_WHY_SUGGEST_TOP_N candidates within
    KANON_WHY_SUGGEST_MAX_DISTANCE Levenshtein edit distance). When no candidates are
    within the threshold, the message states that no close matches were found.

    Args:
        tree: The fully resolved dependency tree.
        argument: The raw argument string from the CLI.

    Returns:
        The single _MatchHit when exactly one category produces a result.

    Raises:
        SystemExit(1): When zero matches are found across all categories (not-found).
        SystemExit(1): When two or more matches are found across categories (ambiguity).
    """
    hits: list[_MatchHit] = []

    # (a) URL category
    url_nodes = _match_by_url(tree, argument)
    for node in url_nodes:
        if node.kind == "source":
            # Source nodes matched by URL use the raw source URL as the label.
            url_label = node.url or argument
        else:
            assert node.canonical_url is not None, (
                f"project node {node.name!r} matched by URL but has no canonical_url (internal invariant)"
            )
            url_label = node.canonical_url
        hits.append(
            _MatchHit(
                category="url", label=f"{'source' if node.kind == 'source' else 'project'} URL '{url_label}'", node=node
            )
        )

    # (b) XML path category
    xml_nodes = _match_by_xml_path(tree, argument)
    for node in xml_nodes:
        hits.append(_MatchHit(category="xml_path", label=f"XML manifest path '{node.ref}'", node=node))

    # (c) Source name category
    src_nodes = _match_by_source_name(tree, argument)
    for node in src_nodes:
        hits.append(_MatchHit(category="source_name", label=f"source name '{node.name}'", node=node))

    if len(hits) == 0:
        universe = _build_suggestion_universe(tree)
        suggestions = _suggest_closest_matches(
            argument,
            universe,
            max_distance=KANON_WHY_SUGGEST_MAX_DISTANCE,
            top_n=KANON_WHY_SUGGEST_TOP_N,
        )
        if suggestions:
            suggestion_lines = "\n".join(f"  {s}" for s in suggestions)
            print(
                f"ERROR: {argument} not found in resolved tree\nDid you mean one of:\n{suggestion_lines}",
                file=sys.stderr,
            )
        else:
            print(
                f"ERROR: {argument} not found in resolved tree\nNo close matches found.",
                file=sys.stderr,
            )
        sys.exit(1)

    if len(hits) >= 2:
        interpretations = "; ".join(h.label for h in hits)
        print(
            f"ERROR: argument '{argument}' is ambiguous -- matches multiple categories: {interpretations}.\n"
            "Pass the argument in its canonical form to disambiguate (e.g., use the full "
            "canonical project URL for URL matching, or the exact XML manifest path for "
            "XML-path matching, or the exact source name token for source-name matching).",
            file=sys.stderr,
        )
        sys.exit(1)

    return hits[0]


# ---------------------------------------------------------------------------
# Closest-match suggestion (spec Section 4.5 step 5)
# ---------------------------------------------------------------------------


def _build_suggestion_universe(tree: ResolvedTree) -> list[str]:
    """Build the universe of candidate strings for closest-match suggestions.

    The universe is the union of:
    - Every top-level source name (as stored in the tree, not normalized).
    - Every include node's path_in_repo value (XML manifest paths).
    - Every project node's canonical_url value.

    Args:
        tree: The fully resolved dependency tree.

    Returns:
        A list of all candidate strings (may contain duplicates if the tree
        has repeated entries, but duplicates are harmless for the suggester).
    """
    candidates: list[str] = []

    def _collect(node: ChainNode) -> None:
        if node.kind == "source":
            candidates.append(node.name)
        elif node.kind == "include" and node.ref is not None:
            candidates.append(node.ref)
        elif node.kind == "project" and node.canonical_url is not None:
            candidates.append(node.canonical_url)
        for child in node.children:
            _collect(child)

    for source_node in tree.sources:
        _collect(source_node)

    return candidates


def _suggest_closest_matches(
    argument: str,
    universe: list[str],
    max_distance: int,
    top_n: int,
) -> list[str]:
    """Return the top closest matches from the universe to the argument.

    Only candidates with Levenshtein edit distance <= max_distance are eligible.
    Results are sorted ascending by (distance, candidate_value) for deterministic
    output, and truncated to at most top_n entries.

    Args:
        argument: The string to compare against.
        universe: The list of candidate strings to search.
        max_distance: Maximum edit distance for a candidate to be eligible.
        top_n: Maximum number of candidates to return.

    Returns:
        A list of at most top_n candidate strings, sorted ascending by
        (distance, lexicographic value). Empty list when no candidate is
        within max_distance.
    """
    scored: list[tuple[int, str]] = []
    for candidate in universe:
        dist = levenshtein_distance(argument, candidate)
        if dist <= max_distance:
            scored.append((dist, candidate))

    scored.sort(key=lambda pair: (pair[0], pair[1]))
    return [candidate for _, candidate in scored[:top_n]]


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------


def _node_display(node: ChainNode) -> str:
    """Format a single node for the text-format chain display.

    Rules:
      - Source nodes: just the source name (no '@sha' -- it is the anchor).
      - Include nodes: '<name>@<sha>' where name is the path_in_repo value.
      - Project nodes: '<name>@<sha>'.

    Args:
        node: The ChainNode to format.

    Returns:
        The display string for this node.
    """
    if node.kind == "source":
        return node.name
    if node.kind == "include":
        label = node.ref if node.ref else node.name
        return f"{label}@{node.sha}"
    # project
    return f"{node.name}@{node.sha}"


def _render_text(chains: list[list[ChainNode]]) -> list[str]:
    """Render a list of chains to the text-format output lines.

    Each chain becomes one line of the form:
      <source> -> <include>@<sha> -> ... -> <project>@<sha>

    Args:
        chains: A list of chains, each chain being a list of ChainNode objects.

    Returns:
        A list of formatted line strings (one per chain), without trailing newlines.
    """
    lines: list[str] = []
    for chain in chains:
        parts = [_node_display(node) for node in chain]
        lines.append(" -> ".join(parts))
    return lines


# ---------------------------------------------------------------------------
# JSON rendering
# ---------------------------------------------------------------------------


def _chain_to_node_dicts(chain: list[ChainNode]) -> list[dict[str, object]]:
    """Convert a single chain (list of ChainNode) into the spec-shaped list of node dicts.

    Each node dict has exactly five keys: kind, name, ref, sha, url.

    Field semantics:
      - kind: one of 'source', 'include', 'project'.
      - name: human-readable identifier of the node.
      - ref: path_in_repo for include nodes; None for source and project nodes.
      - sha: full 40-char hex SHA.
      - url: for project nodes, node.canonical_url (canonicalized via canonicalize_repo_url);
             for source nodes, node.url (raw URL as stored in the lockfile);
             for include nodes, None (XML manifest paths have no standalone URL).

    Args:
        chain: A list of ChainNode objects representing one resolved chain.

    Returns:
        A list of node dicts suitable for JSON serialization.
    """
    result: list[dict[str, object]] = []
    for node in chain:
        # For project nodes, emit the canonicalized URL so the JSON output
        # matches the text-renderer and the spec (Section 4.5 step 4).
        if node.kind == "project":
            url_value: object = node.canonical_url
        else:
            url_value = node.url
        result.append(
            {
                "kind": node.kind,
                "name": node.name,
                "ref": node.ref,
                "sha": node.sha,
                "url": url_value,
            }
        )
    return result


def _build_why_payload(chains: list[list[ChainNode]]) -> list[list[dict[str, object]]]:
    """Build the JSON-serialisable payload for a list of chains.

    Returns a nested list: the outer list contains one element per chain;
    each inner list contains one node-dict per hop.

    Args:
        chains: A list of chains, each chain being a list of ChainNode objects.

    Returns:
        A list-of-lists of dicts ready for JSON serialisation.
    """
    return [_chain_to_node_dicts(chain) for chain in chains]


def _render_json(chains: list[list[ChainNode]]) -> str:
    """Render a list of chains to a JSON string (spec Section 4.5 step 4).

    The output is a top-level JSON array of chains. Each chain is a list of
    node objects with exactly five keys: kind, name, ref, sha, url.

    Kept for backward compatibility with callers that need the serialised
    string directly (e.g. unit tests).  The :func:`run_why` handler calls
    :func:`_emit_json_payload` via :func:`_build_why_payload` directly.

    Args:
        chains: A list of chains, each chain being a list of ChainNode objects.

    Returns:
        A JSON string representation of all chains, terminated with a newline.
    """
    return json.dumps(_build_why_payload(chains), sort_keys=False, indent=KANON_WHY_JSON_INDENT) + "\n"


# ---------------------------------------------------------------------------
# CLI registration
# ---------------------------------------------------------------------------


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'why' subcommand on the top-level argparse subparsers.

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "why",
        add_help=True,
        help="Explain why a project is in the resolved dependency tree.",
        description=(
            "Reads the .kanon file, resolves the full dependency tree\n"
            "(from .kanon.lock when present, else live-resolves against\n"
            "the catalog), and prints every chain reaching the requested\n"
            "node.\n\n"
            "Argument matching (all three categories evaluated):\n"
            "  (a) <project> repo URL -- canonicalized via canonicalize_repo_url.\n"
            "  (b) Transitive XML manifest path -- exact-string equality.\n"
            "  (c) Top-level source name -- normalized via derive_source_name.\n\n"
            "Chain format:\n"
            "  <top-source> -> <xml-path>@<sha> -> ... -> <project>@<sha>\n\n"
            "Catalog source precedence: --catalog-source flag, then\n"
            "KANON_CATALOG_SOURCE env var. Required only when .kanon.lock\n"
            "is absent (live-resolve path)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "target",
        metavar="<project-url-or-name>",
        help=(
            "The project URL, XML manifest path, or source name to look up. "
            "Project URLs are canonicalized via canonicalize_repo_url before matching. "
            "XML manifest paths are matched by exact string equality. "
            "Source names are normalized via derive_source_name (case- and separator-insensitive)."
        ),
    )

    add_catalog_source_arg(parser)

    parser.add_argument(
        "--kanon-file",
        dest="kanon_file",
        default=os.environ.get(KANON_KANON_FILE_ENV, KANON_KANON_FILE_DEFAULT),
        metavar="<path>",
        help=(
            f"Path to the .kanon file. "
            f"Defaults to '{KANON_KANON_FILE_DEFAULT}'. "
            f"Overridden by the {KANON_KANON_FILE_ENV} environment variable; "
            "the CLI flag takes precedence when both are set."
        ),
    )

    parser.add_argument(
        "--lock-file",
        dest="lock_file",
        default=os.environ.get(KANON_LOCK_FILE),
        metavar="<path>",
        help=(
            "Path to the .kanon.lock file. "
            "When present, the tree is built from lockfile entries (no git calls). "
            "When absent, the command live-resolves against the catalog. "
            f"Defaults to <kanon-file>.lock. "
            f"Overridden by the {KANON_LOCK_FILE} environment variable; "
            "the CLI flag takes precedence when both are set."
        ),
    )

    parser.add_argument(
        "--format",
        dest="format",
        default=os.environ.get(KANON_WHY_FORMAT, KANON_WHY_FORMAT_DEFAULT),
        choices=(KANON_WHY_FORMAT_DEFAULT, KANON_WHY_FORMAT_JSON),
        metavar="<format>",
        help=(
            "Output format: 'text' (default) or 'json'. "
            f"Overridden by the {KANON_WHY_FORMAT} environment variable; "
            "the CLI flag takes precedence when both are set."
        ),
    )

    parser.set_defaults(func=run)


# ---------------------------------------------------------------------------
# Command entry point
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    """Execute the 'kanon why' command.

    Reads the .kanon file, resolves the dependency tree (from .kanon.lock
    when present, else live-resolves), finds all chains ending at the
    requested node, and prints them to stdout.

    Argument matching evaluates all three categories (URL, XML path, source name)
    before deciding. Zero matches -> not-found error. Two or more matches ->
    ambiguity hard error. Exactly one match -> chain walker runs.

    Args:
        args: Parsed argparse namespace. Expected attributes:
            - ``target`` (str): the project URL, XML path, or source name to look up.
            - ``kanon_file`` (str): path to the .kanon file.
            - ``lock_file`` (str | None): path to the lockfile, or None.
            - ``catalog_source`` (str | None): catalog source string.
            - ``format`` (str): output format -- 'text' or 'json'.

    Returns:
        0 on success. Non-zero on error (but most errors call sys.exit directly).
    """
    # -- Validate .kanon file existence --
    kanon_path = pathlib.Path(args.kanon_file)
    if not kanon_path.exists():
        print(
            f"ERROR: .kanon file not found: {kanon_path}\n"
            f"Provide a valid path via --kanon-file or the {KANON_KANON_FILE_ENV} env var.",
            file=sys.stderr,
        )
        sys.exit(1)

    # -- Determine lockfile path --
    # Use the shared three-tier derivation: CLI flag > KANON_LOCK_FILE env > derived default.
    resolved_lock_path = derive_lock_file_path(
        cli_lock_file=pathlib.Path(args.lock_file) if args.lock_file else None,
        env_lock_file=os.environ.get(KANON_LOCK_FILE),
        kanon_file_path=kanon_path,
    )
    # Fail fast when the user explicitly specifies --lock-file and the path does not exist.
    if args.lock_file is not None and not resolved_lock_path.exists():
        print(
            f"ERROR: lock file not found: {args.lock_file}",
            file=sys.stderr,
        )
        sys.exit(1)
    # Only treat the path as present when the file actually exists.
    if resolved_lock_path.exists():
        lock_file_path: pathlib.Path | None = resolved_lock_path
    else:
        lock_file_path = None

    # -- Resolve the tree --
    if lock_file_path is not None and lock_file_path.exists():
        # Lockfile path: no network calls, read SHAs from lockfile directly.
        lockfile = read_lockfile(lock_file_path)
        tree = _build_tree_from_lockfile(lockfile)
    else:
        # Live-resolve path: requires catalog source.
        if not args.catalog_source:
            print(
                MISSING_CATALOG_ERROR_TEMPLATE.format(command="kanon why"),
                file=sys.stderr,
                end="",
            )
            sys.exit(1)
        # Delegate to live resolver.
        try:
            tree = _live_resolve_tree(kanon_path, args.catalog_source)
        except LiveResolveError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

    # -- Resolve the match (all three categories; ambiguity detection) --
    # _resolve_match calls sys.exit(1) on zero matches (not-found) or
    # two-or-more matches (ambiguity). Returns a single _MatchHit on success.
    hit = _resolve_match(tree, args.target)

    # -- Walk all chains from the matched node --
    if hit.category == "url" and hit.node.kind == "project":
        # Project URL match: target_canonical is stored on the project node.
        target_canonical = hit.node.canonical_url
        if target_canonical is None:
            print(
                f"ERROR: matched project node '{hit.node.name}' has no canonical URL (internal error)",
                file=sys.stderr,
            )
            sys.exit(1)
        chains = _walk_chains(tree, target_canonical)
    else:
        # XML path, source name, or source-URL match: walk from the matched node itself.
        chains = _walk_chains_from_node(tree, hit.node)

    if not chains:
        print(
            f"ERROR: {args.target} not found in resolved tree",
            file=sys.stderr,
        )
        sys.exit(1)

    # -- Render and emit output --
    if args.format == KANON_WHY_FORMAT_JSON:
        from kanon_cli.cli import _emit_json_payload

        _emit_json_payload(_build_why_payload(chains), sort_keys=False, indent=KANON_WHY_JSON_INDENT)
    else:
        lines = _render_text(chains)
        for line in lines:
            print(line)

    return 0
