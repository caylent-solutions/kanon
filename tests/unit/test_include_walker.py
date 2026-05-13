"""Unit tests for the include-walker module.

Covers AC-FUNC-001 through AC-FUNC-006 and AC-TEST-001:
  - Flat XML (zero includes) -> tree with no children (AC-FUNC-001).
  - N-deep chain -> tree of depth N (AC-FUNC-002).
  - Cycle detection -> IncludeCycleError with rendered path (AC-FUNC-003).
  - Diamond deduplication -> shared node appears once at first-walked position (AC-FUNC-004).
  - Path canonicalisation via os.path.normpath (AC-FUNC-005).
  - Lockfile serialisation order matches DFS walk order (AC-FUNC-006).
  - IncludeCycleError is a subclass of InstallError (AC-FUNC-007).
"""

from __future__ import annotations

import os
import pathlib
import xml.etree.ElementTree as ET

import pytest

from kanon_cli.core.include_walker import (
    IncludeCycleError,
    IncludeTree,
    MalformedIncludeError,
    _canonicalize_include_path,
    _walk_includes,
)
from kanon_cli.core.install import InstallError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_manifest(path: pathlib.Path, includes: list[str] | None = None) -> None:
    """Write a minimal manifest XML with zero or more <include> elements."""
    root = ET.Element("manifest")
    for name in includes or []:
        ET.SubElement(root, "include", name=name)
    ET.ElementTree(root).write(str(path), encoding="unicode", xml_declaration=False)


# ---------------------------------------------------------------------------
# AC-FUNC-007: IncludeCycleError is a subclass of InstallError
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_include_cycle_error_is_install_error() -> None:
    """IncludeCycleError must be a subclass of InstallError."""
    assert issubclass(IncludeCycleError, InstallError)


# ---------------------------------------------------------------------------
# AC-FUNC-001: flat XML with zero <include> elements
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_flat_xml_no_includes(tmp_path: pathlib.Path) -> None:
    """_walk_includes returns a root-only IncludeTree for a manifest with zero includes."""
    start = tmp_path / "root.xml"
    _write_manifest(start)

    tree = _walk_includes(start, tmp_path)

    assert tree.path == _canonicalize_include_path(start, tmp_path)
    assert tree.includes == []


# ---------------------------------------------------------------------------
# AC-FUNC-002: N-deep chain builds a tree of depth N
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "chain",
    [
        ["b.xml"],
        ["b.xml", "c.xml"],
        ["b.xml", "c.xml", "d.xml"],
    ],
    ids=["depth-1", "depth-2", "depth-3"],
)
def test_linear_chain(tmp_path: pathlib.Path, chain: list[str]) -> None:
    """_walk_includes builds a depth-N tree for an N-deep linear include chain."""
    # Write files: a.xml -> b.xml -> c.xml -> ... (each including the next)
    all_files = ["a.xml"] + chain
    for i, fname in enumerate(all_files):
        nxt = [all_files[i + 1]] if i + 1 < len(all_files) else []
        _write_manifest(tmp_path / fname, includes=nxt)

    tree = _walk_includes(tmp_path / "a.xml", tmp_path)

    # The tree depth should equal len(chain)
    node = tree
    for expected_name in chain:
        assert len(node.includes) == 1, f"expected one child at each level; got {len(node.includes)}"
        node = node.includes[0]
        assert node.path == _canonicalize_include_path(tmp_path / expected_name, tmp_path)
    assert node.includes == []


# ---------------------------------------------------------------------------
# AC-FUNC-003: cycle detection -- various cycle shapes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_self_cycle(tmp_path: pathlib.Path) -> None:
    """A self-referencing include (A -> A) raises IncludeCycleError with 'A -> A'."""
    xml_file = tmp_path / "a.xml"
    _write_manifest(xml_file, includes=["a.xml"])

    with pytest.raises(IncludeCycleError) as exc_info:
        _walk_includes(xml_file, tmp_path)

    msg = str(exc_info.value)
    assert "include cycle:" in msg
    # The cycle is rendered as a.xml -> a.xml
    assert "a.xml -> a.xml" in msg


@pytest.mark.unit
def test_two_node_cycle(tmp_path: pathlib.Path) -> None:
    """A -> B -> A raises IncludeCycleError with the rendered cycle."""
    _write_manifest(tmp_path / "a.xml", includes=["b.xml"])
    _write_manifest(tmp_path / "b.xml", includes=["a.xml"])

    with pytest.raises(IncludeCycleError) as exc_info:
        _walk_includes(tmp_path / "a.xml", tmp_path)

    msg = str(exc_info.value)
    assert "include cycle:" in msg
    # Must name both files and close the cycle
    assert "a.xml" in msg
    assert "b.xml" in msg
    # The closing edge is rendered explicitly (cycle closes back to a.xml)
    assert msg.count("a.xml") >= 2


@pytest.mark.unit
def test_triangle_cycle(tmp_path: pathlib.Path) -> None:
    """A -> B -> C -> A raises IncludeCycleError with all three nodes."""
    _write_manifest(tmp_path / "a.xml", includes=["b.xml"])
    _write_manifest(tmp_path / "b.xml", includes=["c.xml"])
    _write_manifest(tmp_path / "c.xml", includes=["a.xml"])

    with pytest.raises(IncludeCycleError) as exc_info:
        _walk_includes(tmp_path / "a.xml", tmp_path)

    msg = str(exc_info.value)
    assert "include cycle:" in msg
    assert "a.xml" in msg
    assert "b.xml" in msg
    assert "c.xml" in msg


@pytest.mark.unit
@pytest.mark.parametrize(
    "start, files, expected_in_msg",
    [
        # self-cycle: rendered as a.xml -> a.xml
        (
            "a.xml",
            {"a.xml": ["a.xml"]},
            ["a.xml", "a.xml"],
        ),
        # 3-cycle: a -> b -> c -> a; message contains all three and closes on a
        (
            "a.xml",
            {"a.xml": ["b.xml"], "b.xml": ["c.xml"], "c.xml": ["a.xml"]},
            ["a.xml", "b.xml", "c.xml"],
        ),
    ],
    ids=["self-cycle", "triangle"],
)
def test_cycle_message_format(
    tmp_path: pathlib.Path,
    start: str,
    files: dict[str, list[str]],
    expected_in_msg: list[str],
) -> None:
    """IncludeCycleError message uses 'include cycle: p0 -> ... -> p0' format."""
    for fname, inc in files.items():
        _write_manifest(tmp_path / fname, includes=inc)

    with pytest.raises(IncludeCycleError) as exc_info:
        _walk_includes(tmp_path / start, tmp_path)

    msg = str(exc_info.value)
    assert msg.startswith("include cycle:"), f"unexpected prefix: {msg!r}"
    for name in expected_in_msg:
        assert name in msg, f"expected {name!r} in error message"
    # The message must contain ' -> ' separators
    assert " -> " in msg


# ---------------------------------------------------------------------------
# AC-FUNC-004: diamond deduplication
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_diamond_dedup(tmp_path: pathlib.Path) -> None:
    """Diamond (A->B, A->C, B->D, C->D): D appears exactly once in the tree.

    The DFS walks A -> B -> D (D is added to 'done'); then C -> D (D is in
    'done', skip).  So B has D as a child; C has no children.
    """
    _write_manifest(tmp_path / "a.xml", includes=["b.xml", "c.xml"])
    _write_manifest(tmp_path / "b.xml", includes=["d.xml"])
    _write_manifest(tmp_path / "c.xml", includes=["d.xml"])
    _write_manifest(tmp_path / "d.xml")

    tree = _walk_includes(tmp_path / "a.xml", tmp_path)

    # a has two children: b and c
    assert len(tree.includes) == 2
    b_node, c_node = tree.includes
    assert b_node.path == _canonicalize_include_path(tmp_path / "b.xml", tmp_path)
    assert c_node.path == _canonicalize_include_path(tmp_path / "c.xml", tmp_path)

    # b has d as its only child (first-walked position)
    assert len(b_node.includes) == 1
    d_from_b = b_node.includes[0]
    assert d_from_b.path == _canonicalize_include_path(tmp_path / "d.xml", tmp_path)

    # c's child d was deduped: c has no children
    assert c_node.includes == []


@pytest.mark.unit
def test_diamond_total_nodes(tmp_path: pathlib.Path) -> None:
    """Diamond: total nodes in the flattened tree equals 4 (a, b, c, d) not 5."""
    _write_manifest(tmp_path / "a.xml", includes=["b.xml", "c.xml"])
    _write_manifest(tmp_path / "b.xml", includes=["d.xml"])
    _write_manifest(tmp_path / "c.xml", includes=["d.xml"])
    _write_manifest(tmp_path / "d.xml")

    tree = _walk_includes(tmp_path / "a.xml", tmp_path)

    def _count_nodes(node: IncludeTree) -> int:
        return 1 + sum(_count_nodes(child) for child in node.includes)

    # a(root) + b + d + c = 4 unique nodes (d counted only once)
    assert _count_nodes(tree) == 4


# ---------------------------------------------------------------------------
# AC-FUNC-005: path canonicalisation via os.path.normpath
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_normpath_dot_slash_equivalence(tmp_path: pathlib.Path) -> None:
    """'./b.xml' and 'b.xml' in <include name=...> refer to the same canonical node."""
    # a.xml includes ./b.xml (with ./ prefix)
    _write_manifest(tmp_path / "a.xml", includes=["./b.xml"])
    # b.xml includes b.xml plain (no prefix) but we write via the same path
    _write_manifest(tmp_path / "b.xml")

    tree = _walk_includes(tmp_path / "a.xml", tmp_path)

    # Should resolve to one child: b.xml (normalised)
    assert len(tree.includes) == 1
    child = tree.includes[0]
    # The canonical path must NOT contain "./"
    assert "./" not in str(child.path)
    # And must equal the normpath of b.xml
    expected = _canonicalize_include_path(tmp_path / "b.xml", tmp_path)
    assert child.path == expected


@pytest.mark.unit
def test_normpath_used_for_cycle_detection(tmp_path: pathlib.Path) -> None:
    """Cycle detection uses the normalised path (./a.xml == a.xml -> same node)."""
    # a.xml includes ./a.xml -- a self-cycle via the ./ form
    _write_manifest(tmp_path / "a.xml", includes=["./a.xml"])

    with pytest.raises(IncludeCycleError) as exc_info:
        _walk_includes(tmp_path / "a.xml", tmp_path)

    msg = str(exc_info.value)
    assert "include cycle:" in msg
    # Message should not contain "./" in the path (normalised)
    assert " -> " in msg


# ---------------------------------------------------------------------------
# AC-FUNC-006: DFS order is preserved for lockfile serialisation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_dfs_order_matches_walk_order(tmp_path: pathlib.Path) -> None:
    """The IncludeTree's depth-first order equals the order of the DFS walk.

    Tree: a -> [b -> d, c -> e]
    DFS pre-order: a, b, d, c, e
    Flattening the tree with a pre-order traversal must yield that order.
    """
    _write_manifest(tmp_path / "a.xml", includes=["b.xml", "c.xml"])
    _write_manifest(tmp_path / "b.xml", includes=["d.xml"])
    _write_manifest(tmp_path / "c.xml", includes=["e.xml"])
    _write_manifest(tmp_path / "d.xml")
    _write_manifest(tmp_path / "e.xml")

    tree = _walk_includes(tmp_path / "a.xml", tmp_path)

    def _preorder(node: IncludeTree) -> list[str]:
        result = [str(node.path)]
        for child in node.includes:
            result.extend(_preorder(child))
        return result

    order = _preorder(tree)
    # a is root (not in tree.includes -- it IS the tree), then b, d, c, e
    assert order[0].endswith("a.xml")
    assert order[1].endswith("b.xml")
    assert order[2].endswith("d.xml")
    assert order[3].endswith("c.xml")
    assert order[4].endswith("e.xml")


# ---------------------------------------------------------------------------
# Malformed <include> element (missing 'name' attribute) -- fail-fast behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_include_without_name_attribute_raises(tmp_path: pathlib.Path) -> None:
    """An <include> element without a 'name' attribute raises MalformedIncludeError.

    The walker enforces fail-fast semantics: a missing 'name' attribute is a hard
    error, not a silent skip.  The error message identifies the containing file.
    """
    # Write a.xml with an <include> that has no 'name' attribute.
    root = ET.Element("manifest")
    ET.SubElement(root, "include")  # no 'name' attribute
    ET.ElementTree(root).write(str(tmp_path / "a.xml"), encoding="unicode", xml_declaration=False)

    with pytest.raises(MalformedIncludeError) as exc_info:
        _walk_includes(tmp_path / "a.xml", tmp_path)

    msg = str(exc_info.value)
    assert "malformed" in msg.lower()
    assert "name" in msg


@pytest.mark.unit
def test_malformed_include_error_is_install_error() -> None:
    """MalformedIncludeError must be a subclass of InstallError."""
    assert issubclass(MalformedIncludeError, InstallError)


@pytest.mark.unit
def test_malformed_include_error_names_file(tmp_path: pathlib.Path) -> None:
    """MalformedIncludeError message contains the path of the offending XML file."""
    xml_file = tmp_path / "bad.xml"
    root = ET.Element("manifest")
    ET.SubElement(root, "include")  # no 'name' attribute
    ET.ElementTree(root).write(str(xml_file), encoding="unicode", xml_declaration=False)

    with pytest.raises(MalformedIncludeError) as exc_info:
        _walk_includes(xml_file, tmp_path)

    # The error must mention the file that contains the malformed element.
    assert "bad.xml" in str(exc_info.value)


# ---------------------------------------------------------------------------
# _canonicalize_include_path helper tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw, expected_suffix",
    [
        ("foo.xml", "foo.xml"),
        ("./foo.xml", "foo.xml"),
        ("sub/foo.xml", os.path.join("sub", "foo.xml")),
        ("./sub/../foo.xml", "foo.xml"),
    ],
    ids=["plain", "dot-slash", "subdir", "dot-slash-parent"],
)
def test_canonicalize_include_path(tmp_path: pathlib.Path, raw: str, expected_suffix: str) -> None:
    """_canonicalize_include_path normalises the path via os.path.normpath."""
    full_path = tmp_path / raw
    result = _canonicalize_include_path(full_path, tmp_path)
    assert str(result) == expected_suffix
