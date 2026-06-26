"""Transitive <include> resolver with cycle detection and diamond deduplication.

Public API:
  - ``_walk_includes(start_xml_path, manifest_repo) -> IncludeTree``:
    Depth-first walker that resolves transitive ``<include>`` chains, detects
    cycles, and deduplicates diamond paths.
  - ``IncludeCycleError``: Raised when the walker detects an include cycle.
  - ``MalformedIncludeError``: Raised when an ``<include>`` element lacks the
    required ``name`` attribute.
  - ``IncludeTree``: Dataclass representing a node in the resolved include tree.
  - ``_canonicalize_include_path(path, manifest_repo)``: Helper that normalises
    an absolute include path to a repo-relative ``pathlib.Path`` via
    ``os.path.normpath``.

Cycle detection algorithm (spec Section 4.7):
  The walker maintains two sets:
  - ``active_path``: ordered list of canonical repo-relative paths on the
    current DFS branch (ancestors of the node being visited).
  - ``done``: set of canonical repo-relative paths whose subtrees have been
    fully processed.

  On each node visit:
  1. Canonicalise the absolute path to a repo-relative path.
  2. If the canonical path is already in ``active_path``: CYCLE -- raise
     ``IncludeCycleError`` with the rendered cycle string.
  3. If the canonical path is already in ``done``: DIAMOND -- skip (no-op for
     include traversal; the node was already fully processed at its
     first-visited position).
  4. Otherwise: push to ``active_path``, recurse into children, pop from
     ``active_path``, add to ``done``.

Diamond deduplication note:
  When a node is encountered a second time via a different parent (diamond),
  it is already in ``done`` and the current parent receives no child entry for
  it. The node appears only at its first-walked position in the tree. This
  matches the lockfile serialisation rule: ``[[sources.includes]]`` entries
  appear at their first DFS position only.

Error message format (spec Section 4.7):
  ``"include cycle: <p0> -> <p1> -> ... -> <pn> -> <p0>"``
  All paths are repo-relative (not absolute), making the message portable
  across operator machines.
"""

from __future__ import annotations

import os
import pathlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


class InstallError(Exception):
    """Base class for all install state-machine hard errors.

    Subclasses carry structured payloads (summary, context, remediation) and
    render via ``str(err)`` to the spec's standard three-line error shape.

    This class is defined here (in ``include_walker``) rather than in
    ``install.py`` to break the circular import that would arise if
    ``include_walker`` imported from ``install`` and ``install`` imported from
    ``include_walker``.  ``install.py`` imports ``InstallError`` from here
    and re-exports it so existing call-sites continue to work.
    """


class MalformedIncludeError(InstallError):
    """Raised when an ``<include>`` element is missing the required ``name`` attribute.

    The walker enforces fail-fast semantics: a malformed ``<include>`` element
    (one without a ``name`` attribute) is not silently skipped.  The error
    message identifies the XML file containing the malformed element so the
    operator can locate and fix it.

    Args:
        xml_file: Repo-relative or absolute path to the XML file containing
            the malformed ``<include>`` element.
    """

    def __init__(self, xml_file: pathlib.Path) -> None:
        self.xml_file = xml_file
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"ERROR: malformed <include> element in {self.xml_file}: "
            "missing required 'name' attribute.\n"
            "  Every <include> element must have a 'name' attribute specifying "
            "the path to the included XML file.\n"
            '  Remediation: add name="<path/to/file.xml>" to the malformed element.'
        )


class IncludeCycleError(InstallError):
    """Raised when ``_walk_includes`` detects a cycle in the ``<include>`` chain.

    The ``message`` attribute contains the full rendered cycle string in the
    format ``"include cycle: <p0> -> <p1> -> ... -> <p0>"``, using repo-relative
    paths so the message is portable across operator machines.

    Args:
        cycle_path: Ordered list of repo-relative path strings on the active
            DFS branch at the point the cycle is detected. The last element is
            the canonical path that was already on the active path (the start of
            the cycle). The closing edge is appended explicitly so the operator
            sees where the loop closes.
    """

    def __init__(self, cycle_path: list[str]) -> None:
        self.cycle_path = cycle_path
        super().__init__(str(self))

    def __str__(self) -> str:
        return "include cycle: " + " -> ".join(self.cycle_path)


@dataclass
class IncludeTree:
    """A node in the resolved ``<include>`` tree.

    Attributes:
        path: Repo-relative canonical path to the XML file this node represents.
            Canonicalised via ``_canonicalize_include_path``.
        includes: Ordered list of child ``IncludeTree`` nodes, corresponding to
            the ``<include>`` elements in this XML file's DFS walk. Diamond-
            deduped nodes appear only at their first-walked position; subsequent
            references produce no child entry.
    """

    path: pathlib.Path
    includes: list[IncludeTree] = field(default_factory=list)


def _canonicalize_include_path(path: pathlib.Path, manifest_repo: pathlib.Path) -> pathlib.Path:
    """Return the repo-relative canonical form of an absolute include path.

    Applies ``os.path.normpath`` to resolve ``./`` prefixes, ``..`` segments,
    and redundant separators. The result is relative to ``manifest_repo``,
    making it portable across operator machines.

    Args:
        path: Absolute filesystem path to an XML include file.
        manifest_repo: Absolute path to the root of the manifest repository.
            Used to compute the repo-relative form.

    Returns:
        A ``pathlib.Path`` containing the normalised repo-relative path
        (e.g. ``Path("repo-specs/ci/helpers.xml")`` rather than
        ``Path("/tmp/abc/repo-specs/ci/helpers.xml")``).
    """
    relative = path.relative_to(manifest_repo)
    normalised = os.path.normpath(str(relative))
    return pathlib.Path(normalised)


def _walk_includes(start_xml_path: pathlib.Path, manifest_repo: pathlib.Path) -> IncludeTree:
    """Walk ``<include>`` chains depth-first, detecting cycles and deduplicating diamonds.

    Implements the two-set DFS algorithm described in the module docstring.

    Args:
        start_xml_path: Absolute path to the root XML manifest file.
        manifest_repo: Absolute path to the root of the manifest repository.
            Used to resolve ``<include name=...>`` attributes (which are relative
            to the manifest repo root, not to the including file's directory) and
            to canonicalise paths for cycle detection.

    Returns:
        An ``IncludeTree`` rooted at the canonical path of ``start_xml_path``.
        The tree's ``includes`` list follows DFS pre-order; diamond-deduped
        nodes appear only at their first-walked position.

    Raises:
        IncludeCycleError: If the walker discovers that a node already on the
            active DFS path is referenced again (direct or transitive cycle).
            The error message renders the full cycle using repo-relative paths.
        MalformedIncludeError: If an ``<include>`` element is missing the
            required ``name`` attribute.  The error names the containing file.
        FileNotFoundError: If an ``<include>`` references a file that does not
            exist under ``manifest_repo``.
        xml.etree.ElementTree.ParseError: If any XML file is malformed.
    """

    active_path: list[pathlib.Path] = []

    done: set[pathlib.Path] = set()

    def _visit(abs_path: pathlib.Path) -> IncludeTree:
        canonical = _canonicalize_include_path(abs_path, manifest_repo)

        if canonical in active_path:
            cycle_start_idx = active_path.index(canonical)
            cycle_nodes = active_path[cycle_start_idx:]

            cycle_strs = [str(p) for p in cycle_nodes] + [str(canonical)]
            raise IncludeCycleError(cycle_path=cycle_strs)

        active_path.append(canonical)

        tree = ET.parse(str(abs_path))
        root = tree.getroot()

        child_nodes: list[IncludeTree] = []
        for include_el in root.findall("include"):
            include_name = include_el.get("name")
            if include_name is None:
                raise MalformedIncludeError(xml_file=abs_path)

            child_abs_path = manifest_repo / include_name
            child_canonical = _canonicalize_include_path(child_abs_path, manifest_repo)

            if child_canonical in done:
                continue

            child_node = _visit(child_abs_path)
            child_nodes.append(child_node)

        active_path.pop()
        done.add(canonical)

        return IncludeTree(path=canonical, includes=child_nodes)

    return _visit(start_xml_path)
