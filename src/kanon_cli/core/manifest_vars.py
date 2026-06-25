"""Shared detection of functional ``${VAR}`` placeholders in a manifest tree.

Both ``kanon add`` (detection against the UNRESOLVED catalog manifest) and the
``install`` guard (verification against the RESOLVED, post-envsubst manifest)
must agree on EXACTLY which ``${VAR}`` placeholders matter. A ``${VAR}`` matters
only when it appears in a *functional* attribute value -- one the repo tool
consumes during ``repo sync`` -- namely the attributes of the ``<remote>``
elements a ``<project>`` references (explicitly via ``remote="NAME"`` or via the
``<default>`` remote) and the attributes of the ``<project>`` elements
themselves.

A ``${VAR}`` that appears only in an XML comment, a ``<![CDATA[...]]>`` block,
or element text is documentation prose: the repo tool never substitutes it and
``repo sync`` never consumes it, so it must be ignored. ``xml.etree`` only
exposes attribute values via ``Element.attrib``; comments, CDATA, and element
text never appear there, so scanning ``attrib`` values is functional by
construction.

This module is the single source of truth for "which ``${VAR}`` names are
functional in a manifest + its ``<include>`` tree" so the add-side detector and
the install-side guard stay consistent by construction (DRY).
"""

from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET

from kanon_cli.constants import SHELL_VAR_PATTERN
from kanon_cli.core.include_walker import IncludeTree, _walk_includes


def _vars_in_attributes(element: ET.Element) -> set[str]:
    """Return the ``${VAR}`` names referenced in an element's attribute values.

    Scans every attribute value of ``element`` for ``${VAR}`` placeholders and
    returns the bare ``VAR`` names (without the ``${...}`` wrapper). Because
    ``Element.attrib`` exposes only attribute values -- never comments, CDATA,
    or element text -- this is inherently scoped to functional positions.

    Args:
        element: An XML element whose attribute values are scanned.

    Returns:
        The set of placeholder variable names found across all attributes.
    """
    found: set[str] = set()
    for value in element.attrib.values():
        for match in SHELL_VAR_PATTERN.finditer(value):
            found.add(match.group(1))
    return found


def _collect_include_tree_files(
    include_tree: IncludeTree,
    manifest_root: pathlib.Path,
) -> list[pathlib.Path]:
    """Flatten an ``IncludeTree`` into absolute manifest file paths (DFS pre-order).

    Args:
        include_tree: The resolved include tree for the manifest's root file.
        manifest_root: Absolute path to the manifest repo root that the tree's
            repo-relative ``path`` values resolve against.

    Returns:
        The deduplicated list of absolute manifest file paths in DFS pre-order.
    """
    ordered: list[pathlib.Path] = []
    seen: set[pathlib.Path] = set()

    def _visit(node: IncludeTree) -> None:
        abs_path = manifest_root / node.path
        if abs_path not in seen:
            seen.add(abs_path)
            ordered.append(abs_path)
        for child in node.includes:
            _visit(child)

    _visit(include_tree)
    return ordered


def functional_vars_in_manifest_files(manifest_files: list[pathlib.Path]) -> set[str]:
    """Return the ``${VAR}`` names in functional positions across manifest files.

    Aggregates every ``<remote>`` (keyed by ``name``), every ``<default>``
    remote, and every ``<project>`` across the given manifest files, then
    determines which remotes the projects reference (by explicit
    ``remote="NAME"`` or, when omitted, the ``<default>`` remote). The functional
    var set is the union of the ``${VAR}`` placeholders in those referenced
    remotes' attributes plus any ``${VAR}`` in the projects' own attributes.

    Missing files are skipped (the install guard may be handed a path for a node
    that the include walker recorded but that does not exist on disk).

    Args:
        manifest_files: Absolute paths to the manifest's root file plus its
            ``<include>`` chain, in any order (aggregation is order-independent).

    Returns:
        The set of functional ``${VAR}`` names referenced across the files.

    Raises:
        xml.etree.ElementTree.ParseError: If any manifest file is malformed.
    """
    remotes: dict[str, ET.Element] = {}
    default_remotes: set[str] = set()
    projects: list[ET.Element] = []

    for manifest_file in manifest_files:
        if not manifest_file.is_file():
            continue
        root = ET.parse(str(manifest_file)).getroot()
        for remote_el in root.findall("remote"):
            remote_name = remote_el.get("name")
            if remote_name:
                remotes[remote_name] = remote_el
        for default_el in root.findall("default"):
            default_remote = default_el.get("remote")
            if default_remote:
                default_remotes.add(default_remote)
        projects.extend(root.findall("project"))

    referenced_remotes: set[str] = set()
    detected: set[str] = set()
    for project_el in projects:
        detected |= _vars_in_attributes(project_el)
        project_remote = project_el.get("remote")
        if project_remote:
            referenced_remotes.add(project_remote)
        else:
            referenced_remotes |= default_remotes

    for remote_name in referenced_remotes:
        remote_el = remotes.get(remote_name)
        if remote_el is not None:
            detected |= _vars_in_attributes(remote_el)

    return detected


def detect_functional_manifest_vars(
    root_manifest_path: pathlib.Path,
    manifest_root: pathlib.Path,
) -> set[str]:
    """Return the functional ``${VAR}`` names a root manifest's tree references.

    Resolves the root manifest's ``<include>`` chain via ``_walk_includes``,
    flattens it to absolute file paths, and delegates to
    :func:`functional_vars_in_manifest_files`. This is the entry point both the
    add-side detector and the install-side guard call so they scan the SAME
    functional positions across the SAME include tree.

    Args:
        root_manifest_path: Absolute path to the manifest's root XML file.
        manifest_root: Absolute path to the manifest repo root, used to resolve
            ``<include name=...>`` references.

    Returns:
        The set of functional ``${VAR}`` names referenced across the tree.

    Raises:
        IncludeCycleError: If the manifest's include chain contains a cycle.
        MalformedIncludeError: If an ``<include>`` element lacks a ``name``.
        xml.etree.ElementTree.ParseError: If any manifest file is malformed.
    """
    include_tree = _walk_includes(root_manifest_path, manifest_root)
    manifest_files = _collect_include_tree_files(include_tree, manifest_root)
    return functional_vars_in_manifest_files(manifest_files)
