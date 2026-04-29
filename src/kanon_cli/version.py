"""Fuzzy version resolution using git ls-remote and PEP 440 specifiers.

Resolves version specifiers like ``refs/tags/~=1.0.0``,
``refs/tags/prefix/>=1.0.0,<2.0.0``, ``refs/tags/*`` against available git
tags using the ``packaging`` library.

Supports the same constraint syntax as rpm-git-repo manifest ``<project>``
revision attributes:
- Operators: ~=, >=, <=, >, <, ==, !=
- Wildcard: *
- Range constraints: >=1.0.0,<2.0.0
- Prefixed: refs/tags/~=1.0.0 or refs/tags/prefix/~=1.0.0
"""

import subprocess
import sys

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from kanon_cli.constants import PEP440_OPERATORS


def is_version_constraint(rev_spec: str) -> bool:
    """Return True if the last path component of rev_spec is a PEP 440 constraint.

    Examines only the last path component (after the final ``/``) so that
    prefixed constraints like ``refs/tags/~=1.0.0`` are detected correctly.

    Also detects malformed constraints that start with a single ``=`` (which
    is not a valid PEP 440 operator but is a common typo for ``==``). These
    are returned as True so that the resolution path can reject them with an
    ``invalid version constraint`` error rather than silently passing them
    through as plain branch names.

    Args:
        rev_spec: A revision string, possibly containing path separators.

    Returns:
        True if the last path component contains PEP 440 constraint syntax
        (valid or recognisably malformed).
    """
    last_component = rev_spec.rsplit("/", 1)[-1]

    if last_component == "*":
        return True

    for op in PEP440_OPERATORS:
        if last_component.startswith(op):
            return True

    # Detect malformed single-equals constraints (e.g. ``=*``, ``=1.0.0``).
    # The single ``=`` operator is not valid PEP 440; ``==`` is the equality
    # operator. Treat these as constraint attempts so the caller receives
    # ``invalid version constraint`` instead of a misleading git error.
    if last_component.startswith("=") and not last_component.startswith("=="):
        return True

    # Range constraints: comma-separated specifiers (e.g. ">=1.0.0,<2.0.0").
    if "," in last_component:
        parts = last_component.split(",")
        return any(part.lstrip().startswith(op) for part in parts for op in PEP440_OPERATORS)

    return False


def resolve_version(url: str, rev_spec: str) -> str:
    """Resolve a version specifier against git tags.

    Supports PEP 440 constraint syntax in the last path component, mirroring
    the constraint resolution in rpm-git-repo manifest ``<project>`` blocks.
    The constraint may optionally be prefixed with a tag path:

    - ``~=1.0.0`` -- bare constraint, resolves against all tags
    - ``refs/tags/~=1.0.0`` -- resolves against tags under refs/tags/
    - ``refs/tags/dev/python/my-lib/~=1.0.0`` -- resolves under a namespace

    The returned value is a full tag ref (e.g. ``refs/tags/1.1.2``) suitable
    for use with ``repo init -b``.

    Plain branch or tag names (no PEP 440 operators) pass through unchanged.

    Args:
        url: Git repository URL.
        rev_spec: Branch, tag, or PEP 440 constraint (optionally prefixed).

    Returns:
        The resolved full tag ref, or rev_spec unchanged if not a constraint.

    Raises:
        SystemExit: If no matching version is found or git ls-remote fails.
    """
    if not is_version_constraint(rev_spec):
        return rev_spec

    tags = _list_tags(url)
    if not tags:
        print(f"Error: No tags found for {url}", file=sys.stderr)
        sys.exit(1)

    try:
        return _resolve_constraint_from_tags(rev_spec, tags)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _resolve_constraint_from_tags(revision: str, available_tags: list[str]) -> str:
    """Resolve a PEP 440 version constraint to the highest matching tag.

    Splits the revision into a prefix and constraint, filters available_tags
    by the prefix, parses version suffixes with packaging.version.Version,
    evaluates the constraint with packaging.specifiers.SpecifierSet, and
    returns the full tag name of the highest matching version.

    This is the canonical constraint resolution implementation. Both
    ``resolve_version`` (CLI, fetches its own tags) and the repo module's
    ``resolve_version_constraint`` (receives pre-fetched tags) delegate here.

    Args:
        revision: A revision string with a PEP 440 constraint in the last
            path component, optionally prefixed.
            Example: ``refs/tags/dev/python/my-lib/~=1.2.0``
        available_tags: List of full tag ref strings to resolve against.
            Example: ``["refs/tags/dev/python/my-lib/1.0.0", ...]``

    Returns:
        The full tag name of the highest version that satisfies the constraint.

    Raises:
        ValueError: If the revision is empty or whitespace, if no available
            tag matches the constraint, if the constraint string is invalid,
            or if no parseable version tags exist under the prefix.
    """
    if not revision or not revision.strip():
        raise ValueError(f"revision must not be empty; received {revision!r}")

    # Split revision into prefix and constraint at the last '/'.
    if "/" in revision:
        prefix, constraint_str = revision.rsplit("/", 1)
        tag_prefix = prefix + "/"
        candidate_tags = [t for t in available_tags if t.startswith(tag_prefix)]
    else:
        prefix = None
        constraint_str = revision
        candidate_tags = list(available_tags)

    if not candidate_tags:
        raise ValueError(f"No tags found under prefix '{prefix}' for the given revision")

    # Parse version from the last path component of each candidate.
    versions = []
    for tag in candidate_tags:
        version_str = tag.rsplit("/", 1)[-1]
        try:
            versions.append((tag, Version(version_str)))
        except InvalidVersion:
            continue

    if not versions:
        raise ValueError(f"No parseable version tags found under '{prefix or 'refs/tags'}'")

    # Wildcard: return highest version.
    if constraint_str == "*":
        return max(versions, key=lambda pair: pair[1])[0]

    # Strip standalone wildcard parts from compound constraints.
    # A bare * combined with range specifiers (e.g. >=1.0.0,<2.0.0,*) is
    # redundant -- it means "any version" within the range -- but is not a
    # valid PEP 440 specifier for SpecifierSet. Remove it before parsing.
    if "," in constraint_str:
        parts = [p.strip() for p in constraint_str.split(",")]
        filtered_parts = [p for p in parts if p != "*"]
        constraint_str = ",".join(filtered_parts)

    try:
        specifier = SpecifierSet(constraint_str)
    except InvalidSpecifier:
        raise ValueError(f"invalid version constraint '{constraint_str}'")

    matching = [(tag, ver) for tag, ver in versions if ver in specifier]

    if not matching:
        raise ValueError(
            f"No tag matching '{constraint_str}' found under "
            f"'{prefix or 'refs/tags'}'. "
            f"Available versions: {[str(v) for _, v in versions]}"
        )

    return max(matching, key=lambda pair: pair[1])[0]


def _list_tags(url: str) -> list[str]:
    """Run ``git ls-remote --tags`` and return full tag ref names.

    Returns full refs (e.g. ``refs/tags/1.1.2``) so callers can use the
    returned value directly with ``repo init -b``.

    Args:
        url: Git repository URL.

    Returns:
        List of full tag ref strings.

    Raises:
        SystemExit: If git ls-remote fails.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", url],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print(
            "Error: git binary not found. Install git and ensure it is on PATH.",
            file=sys.stderr,
        )
        sys.exit(1)
    if result.returncode != 0:
        print(
            f"Error: git ls-remote failed for {url}: {result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)

    tags = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        ref = parts[1]
        if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            tags.append(ref)
    return tags
