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
import os
import pathlib
import sys
from dataclasses import dataclass, field

from kanon_cli.constants import (
    KANON_KANON_FILE_DEFAULT,
    KANON_KANON_FILE_ENV,
    KANON_LOCK_FILE,
    KANON_WHY_FORMAT,
    KANON_WHY_FORMAT_DEFAULT,
    KANON_WHY_SUGGEST_MAX_DISTANCE,
    KANON_WHY_SUGGEST_TOP_N,
    MISSING_CATALOG_ERROR_TEMPLATE,
)
from kanon_cli.utils.levenshtein import levenshtein_distance
from kanon_cli.core.cli_args import add_catalog_source_arg
from kanon_cli.core.lockfile import Lockfile, IncludeEntry, read_lockfile
from kanon_cli.core.metadata import derive_source_name
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
        children: Direct child nodes (populated when building the tree from the lockfile).
    """

    kind: str
    name: str
    ref: str | None
    sha: str
    url: str | None
    canonical_url: str | None = None
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
# Live tree resolution (placeholder -- requires catalog + full install machinery)
# ---------------------------------------------------------------------------


def _live_resolve_tree(kanon_file: pathlib.Path, catalog_source: str) -> ResolvedTree:
    """Resolve the dependency tree live against the catalog.

    This path is used when no .kanon.lock is present. Requires a catalog source.

    Args:
        kanon_file: Path to the .kanon configuration file.
        catalog_source: The catalog source string in '<git-url>@<ref>' format.

    Returns:
        A ResolvedTree populated from the live-resolved manifest XML.

    Raises:
        NotImplementedError: The live-resolve path is not yet implemented in T1.
            T1 scopes only to the lockfile path; the live-resolve path is fully
            implemented in later tasks when the install machinery is extended.
    """
    raise NotImplementedError(
        "ERROR: Live-resolution of the dependency tree is not yet implemented.\n"
        "Provide a .kanon.lock file (run 'kanon install' to generate one) and "
        "re-run 'kanon why' to use the lockfile path."
    )


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
    For source nodes, chains include all descendants under that source.
    For include nodes, chains include the include node and all project nodes under it.

    Args:
        tree: The fully resolved dependency tree.
        target_node: The ChainNode (source or include kind) to find and report chains for.

    Returns:
        A list of chains. Each chain is a list of ChainNode objects starting from
        a top-level source down to a leaf project node that passes through target_node.
        When target_node is a source node, returns all chains starting at that source.
        When target_node is an include node, returns all chains passing through it.
        Returns an empty list when no chains pass through the target node.
    """
    found_chains: list[list[ChainNode]] = []

    def _dfs_collect_all_leaves(node: ChainNode, path: list[ChainNode]) -> None:
        """Collect all chains from the current node to every leaf (project) descendant."""
        current_path = path + [node]
        if node.kind == "project":
            found_chains.append(current_path)
            return
        for child in node.children:
            _dfs_collect_all_leaves(child, current_path)

    def _dfs_find(node: ChainNode, path: list[ChainNode]) -> None:
        """Walk the tree looking for target_node; once found, collect all descendant chains."""
        if node is target_node:
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
    """Match the argument against project nodes by canonicalized URL.

    Attempts to canonicalize the argument. If canonicalization fails (argument is
    not a valid URL), returns an empty list -- no match in this category.

    Args:
        tree: The fully resolved dependency tree.
        argument: The raw argument string from the CLI.

    Returns:
        List of project ChainNode objects whose canonical_url equals
        canonicalize_repo_url(argument). Empty when no match or when
        canonicalization raises ValueError.
    """
    try:
        target_canonical = canonicalize_repo_url(argument)
    except ValueError:
        return []

    matches: list[ChainNode] = []

    def _collect_projects(node: ChainNode) -> None:
        if node.kind == "project" and node.canonical_url == target_canonical:
            matches.append(node)
        for child in node.children:
            _collect_projects(child)

    for source_node in tree.sources:
        _collect_projects(source_node)

    return matches


def _match_by_xml_path(tree: ResolvedTree, argument: str) -> list[ChainNode]:
    """Match the argument against include nodes by exact path_in_repo string equality.

    Args:
        tree: The fully resolved dependency tree.
        argument: The raw argument string from the CLI.

    Returns:
        List of include ChainNode objects whose ref (path_in_repo) exactly equals
        the argument. Empty when no match.
    """
    matches: list[ChainNode] = []

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
        assert node.canonical_url is not None, (
            f"project node {node.name!r} matched by URL but has no canonical_url (internal invariant)"
        )
        url_label = node.canonical_url
        hits.append(_MatchHit(category="url", label=f"project URL '{url_label}'", node=node))

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
# CLI registration
# ---------------------------------------------------------------------------


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the 'why' subcommand on the top-level argparse subparsers.

    Args:
        subparsers: The subparsers action from the top-level parser.
    """
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "why",
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
        choices=(KANON_WHY_FORMAT_DEFAULT,),
        metavar="<format>",
        help=(
            "Output format: 'text' (default). "
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
            - ``format`` (str): output format -- 'text'.

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
        # Delegate to live resolver (not yet implemented in T1).
        try:
            tree = _live_resolve_tree(kanon_path, args.catalog_source)
        except NotImplementedError:
            print(
                "ERROR: Live-resolution is not yet implemented. Run kanon install to generate a lockfile.",
                file=sys.stderr,
            )
            sys.exit(1)

    # -- Resolve the match (all three categories; ambiguity detection) --
    # _resolve_match calls sys.exit(1) on zero matches (not-found) or
    # two-or-more matches (ambiguity). Returns a single _MatchHit on success.
    hit = _resolve_match(tree, args.target)

    # -- Walk all chains from the matched node --
    if hit.category == "url":
        # URL match: target_canonical is stored on the node
        target_canonical = hit.node.canonical_url
        if target_canonical is None:
            print(
                f"ERROR: matched project node '{hit.node.name}' has no canonical URL (internal error)",
                file=sys.stderr,
            )
            sys.exit(1)
        chains = _walk_chains(tree, target_canonical)
    else:
        # XML path or source name match: walk from the matched node itself
        chains = _walk_chains_from_node(tree, hit.node)

    if not chains:
        print(
            f"ERROR: {args.target} not found in resolved tree",
            file=sys.stderr,
        )
        sys.exit(1)

    # -- Render and emit output --
    lines = _render_text(chains)
    for line in lines:
        print(line)

    return 0
