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

    Args:
        rev_spec: A revision string, possibly containing path separators.

    Returns:
        True if the last path component contains PEP 440 constraint syntax.
    """
    last_component = rev_spec.rsplit("/", 1)[-1]

    if last_component == "*":
        return True

    for op in PEP440_OPERATORS:
        if last_component.startswith(op):
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

    - ``~=1.0.0`` — bare constraint, resolves against all tags
    - ``refs/tags/~=1.0.0`` — resolves against tags under refs/tags/
    - ``refs/tags/dev/python/my-lib/~=1.0.0`` — resolves under a namespace

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

    # Split on last '/' to separate prefix from constraint.
    if "/" in rev_spec:
        prefix, constraint_str = rev_spec.rsplit("/", 1)
    else:
        prefix = None
        constraint_str = rev_spec

    tags = _list_tags(url)
    if not tags:
        print(f"Error: No tags found for {url}", file=sys.stderr)
        sys.exit(1)

    # Filter tags by prefix when present.
    if prefix is not None:
        tag_prefix = prefix + "/"
        candidate_tags = [t for t in tags if t.startswith(tag_prefix)]
    else:
        candidate_tags = tags

    if not candidate_tags:
        print(
            f"Error: No tags found under prefix '{prefix}' for {url}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parse version from the last path component of each candidate.
    versions = []
    for tag in candidate_tags:
        version_str = tag.rsplit("/", 1)[-1]
        try:
            versions.append((tag, Version(version_str)))
        except InvalidVersion:
            continue

    if not versions:
        print(
            f"Error: No parseable version tags found under '{prefix or 'refs/tags'}' for {url}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Wildcard: return highest version.
    if constraint_str == "*":
        return max(versions, key=lambda pair: pair[1])[0]

    try:
        specifier = SpecifierSet(constraint_str)
    except InvalidSpecifier:
        print(
            f"Error: Invalid version constraint '{constraint_str}'",
            file=sys.stderr,
        )
        sys.exit(1)

    matching = [(tag, ver) for tag, ver in versions if ver in specifier]

    if not matching:
        print(
            f"Error: No tag matching '{constraint_str}' found under "
            f"'{prefix or 'refs/tags'}' for {url}. "
            f"Available versions: {[str(v) for _, v in versions]}",
            file=sys.stderr,
        )
        sys.exit(1)

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
    result = subprocess.run(
        ["git", "ls-remote", "--tags", url],
        capture_output=True,
        text=True,
        check=False,
    )
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
