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

import enum
import subprocess
import sys

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from kanon_cli.constants import (
    BRANCH_SHA_TRUNCATION_LENGTH,
    KANON_GIT_LS_REMOTE_TIMEOUT,
    PEP440_OPERATORS,
    SHA1_HEX_LENGTH,
    SHA256_HEX_LENGTH,
    SYMREF_HEADS_PREFIX,
    SYMREF_LINE_PREFIX,
    TAG_ERROR_DISPLAY_CAP,
)
from kanon_cli.core.git_runner import run_git_ls_remote


def is_version_constraint(rev_spec: str) -> bool:
    """Return True if the last path component of rev_spec is a PEP 440 constraint.

    Examines only the last path component (after the final ``/``) so that
    prefixed constraints like ``refs/tags/~=1.0.0`` are detected correctly.

    The literal ``latest`` is treated as a constraint that resolves to the
    highest available semver tag (equivalent to wildcard ``*``). This
    matches the catalog-source resolution behaviour in
    ``kanon_cli.core.catalog`` and lets the repo sync path resolve
    ``revision="refs/tags/latest"`` (and the bare form) to a concrete tag
    instead of passing the literal string ``latest`` to ``git fetch``.

    Also detects malformed constraints that start with a single ``=`` (which
    is not a valid PEP 440 operator but is a common typo for ``==``). These
    are returned as True so that the resolution path can reject them with an
    ``invalid version constraint`` error rather than silently passing them
    through as plain branch names.

    Args:
        rev_spec: A revision string, possibly containing path separators.

    Returns:
        True if the last path component contains PEP 440 constraint syntax
        (valid or recognisably malformed) or is the literal ``latest``.
    """
    last_component = rev_spec.rsplit("/", 1)[-1]

    if last_component == "*":
        return True

    if last_component == "latest":
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

    Plain branch or tag names (no PEP 440 operators) pass through unchanged,
    EXCEPT bare PEP 440 version strings (e.g. ``1.0.0``, ``1.0.0a1``,
    ``1.0.0.post1``, ``2026.4.1``, ``1!2.0.0``) which are automatically
    prefixed with ``refs/tags/`` so the underlying ``git fetch`` resolves
    them as tags rather than branch names. Any string that parses cleanly
    via ``packaging.version.Version`` and contains no ``/`` is treated as a
    bare PEP 440 version. Use the ``refs/heads/<branch>`` form explicitly to
    force branch resolution of a numeric branch name.

    Args:
        url: Git repository URL.
        rev_spec: Branch, tag, or PEP 440 constraint (optionally prefixed).

    Returns:
        The resolved full tag ref, or rev_spec unchanged if not a constraint.

    Raises:
        SystemExit: If no matching version is found or git ls-remote fails.
    """
    if not is_version_constraint(rev_spec):
        return _normalize_bare_semver_to_tag(rev_spec)

    tags = _list_tags(url)
    if not tags:
        print(f"Error: No tags found for {url}", file=sys.stderr)
        sys.exit(1)

    try:
        return _resolve_constraint_from_tags(rev_spec, tags)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _is_bare_pep440_version(spec: str) -> bool:
    """Return True if spec parses as a PEP 440 Version and contains no '/'.

    Used to detect bare version strings (e.g. ``1.0.0a1``, ``1!2.0.0``,
    ``1.0.0+local``) that should be normalized to ``refs/tags/<spec>``.
    Inputs containing ``/`` are never bare versions -- they are either
    already-prefixed refs or monorepo-prefixed tags.

    Args:
        spec: A revision string with no leading whitespace.

    Returns:
        True if spec contains no ``/`` and parses cleanly as a
        ``packaging.version.Version``.
    """
    if "/" in spec:
        return False
    try:
        Version(spec)
        return True
    except InvalidVersion:
        return False


def _normalize_bare_semver_to_tag(rev_spec: str) -> str:
    """Prepend ``refs/tags/`` to bare PEP 440 version strings.

    Accepts any input that (a) contains no ``/`` and (b) parses cleanly
    via ``packaging.version.Version``. This widens the previous
    digits-and-dots-only regex to cover all PEP 440 version shapes,
    per spec Section 4.0 rule 3.

    Accepted shapes include (but are not limited to):

    - Plain semver: ``1.0.0``, ``1.0``, ``1``
    - Prereleases: ``1.0.0a1``, ``1.0.0b3``, ``1.0.0rc2``
    - Local versions: ``1.0.0+local``, ``1.0.0+local.build``
    - Calendar versions: ``2026.4.1``
    - Epochs: ``1!2.0.0``
    - Post-releases: ``1.0.0.post1``
    - Dev-releases: ``1.0.0.dev0``

    All other inputs pass through unchanged:

    - Already-prefixed refs: ``refs/tags/1.0.0``, ``refs/heads/main``
    - Branch names that fail PEP 440: ``main``, ``develop``
    - Hex SHAs (40- or 64-char): passed through unchanged
    - Any input containing ``/``: ``feature/foo``, ``subpackage/1.0.0``

    Examples:

    - ``1.0.0``           -> ``refs/tags/1.0.0``
    - ``1.0.0a1``         -> ``refs/tags/1.0.0a1``
    - ``1!2.0.0``         -> ``refs/tags/1!2.0.0``
    - ``main``            -> ``main`` (no change)
    - ``refs/tags/1.0.0`` -> ``refs/tags/1.0.0`` (no change)
    - ``feature/foo``     -> ``feature/foo`` (no change)

    Args:
        rev_spec: A revision string (branch, tag, SHA, or version spec).

    Returns:
        ``refs/tags/<rev_spec>`` when rev_spec is a bare PEP 440 version;
        otherwise ``rev_spec`` unchanged.
    """
    if _is_bare_pep440_version(rev_spec):
        return "refs/tags/" + rev_spec
    return rev_spec


def _format_zero_pep440_tags_error(prefix: str, skipped: list[str]) -> str:
    """Format the loud error message for the zero-PEP-440-parseable-tags case.

    Called when candidate tags exist under ``prefix`` but none of their last
    path components parse as a valid PEP 440 version. Per spec Section 0.4
    and Section 13 decision 14, the message must enumerate the non-PEP-440
    tag names (capped at 10, deterministically sorted) plus a remediation
    pointer to ``kanon catalog audit --check tag-format``.

    Args:
        prefix: The tag namespace prefix that was searched (e.g.
            ``refs/tags/mylib`` or ``refs/tags``).
        skipped: Full tag ref names of every candidate whose last path
            component failed PEP 440 parsing.

    Returns:
        A multi-line error message string (without a trailing newline)
        ready to be passed to ``ValueError``.
    """
    count = len(skipped)
    sorted_skipped = sorted(skipped)
    display = sorted_skipped[:TAG_ERROR_DISPLAY_CAP]
    lines: list[str] = [
        f"ERROR: No PEP 440-parseable version tags found under '{prefix}'.",
        f"Skipped {count} tag(s) whose last path component is not a valid PEP 440 version:",
    ]
    for tag in display:
        lines.append(f"  - {tag}")
    if count > TAG_ERROR_DISPLAY_CAP:
        lines.append(f"... (showing first {TAG_ERROR_DISPLAY_CAP} of {count})")
    lines.append("Run 'kanon catalog audit --check tag-format' against the manifest repo")
    lines.append("to identify every non-PEP-440 tag, then ask the catalog author to rename")
    lines.append("them to PEP 440 form (e.g., 'release-1.0.0' -> '1.0.0').")
    return "\n".join(lines)


def _resolve_constraint_from_tags(revision: str, available_tags: list[str]) -> str:
    """Resolve a PEP 440 version constraint to the highest matching tag.

    Splits the revision into a prefix and constraint, filters available_tags
    by the prefix, parses version suffixes with packaging.version.Version,
    evaluates the constraint with packaging.specifiers.SpecifierSet, and
    returns the full tag name of the highest matching version.

    This is the canonical constraint resolution implementation. Both
    ``resolve_version`` (CLI, fetches its own tags) and the repo module's
    ``resolve_version_constraint`` (receives pre-fetched tags) delegate here.

    Two distinct error variants apply when no PEP 440 versions are found:

    1. Zero candidates under prefix -- ``prefix`` has no tags at all. Raises a
       narrow ``ValueError`` with message ``"No tags found under prefix '<prefix>'
       for the given revision"``. This path is unchanged from before this task.

    2. Candidates exist but none parse as PEP 440 (spec Section 0.4) -- Raises a
       loud ``ValueError`` produced by ``_format_zero_pep440_tags_error``, which
       enumerates up to 10 non-PEP-440 tag names (sorted deterministically) and
       includes a remediation pointer to ``kanon catalog audit --check tag-format``.

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
    # Collect skipped non-PEP-440 tag names for the loud error if needed.
    versions = []
    skipped: list[str] = []
    for tag in candidate_tags:
        version_str = tag.rsplit("/", 1)[-1]
        try:
            versions.append((tag, Version(version_str)))
        except InvalidVersion:
            skipped.append(tag)

    if not versions:
        display_prefix = prefix if prefix is not None else "refs/tags"
        raise ValueError(_format_zero_pep440_tags_error(display_prefix, skipped))

    # Wildcard or 'latest': return highest version. The literal ``latest``
    # is treated as an alias for ``*`` so that ``refs/tags/latest`` and the
    # bare form ``latest`` both resolve to the highest available semver
    # tag, matching the catalog-source contract in
    # ``kanon_cli.core.catalog``.
    if constraint_str in ("*", "latest"):
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


class RevisionShape(enum.Enum):
    """Classification of a REVISION string for 'kanon outdated' column dispatch.

    Values:
        TAG: A PEP 440 version constraint (e.g. ``~=1.0.0``, ``>=1.0.0,<2.0.0``,
            ``*``, ``latest``) or a ``refs/tags/...`` reference. Tag-pinned
            sources use PEP 440 resolution against the remote's tag list.
        BRANCH: A plain branch name (e.g. ``main``, ``develop``, ``feature/foo``)
            that is neither a PEP 440 constraint nor a 40/64-hex-char SHA.
            Branch-pinned sources query the branch HEAD via
            ``git ls-remote refs/heads/<branch>``.
        SHA: A full hexadecimal commit SHA (40 or 64 characters). SHA-pinned
            sources display the same truncated SHA in all columns and have
            ``upgrade-type=none`` (the operator pinned exactly that commit).
    """

    TAG = "tag"
    BRANCH = "branch"
    SHA = "sha"


def _classify_revision_shape(revision: str) -> RevisionShape:
    """Classify a REVISION string into TAG, BRANCH, or SHA.

    Classification rules (applied in order):
    1. If the string is exactly 40 or 64 hex characters, it is SHA-pinned.
    2. If ``is_version_constraint`` returns True or the string starts with
       ``refs/tags/``, it is TAG-pinned.
    3. Otherwise it is BRANCH-pinned.

    Args:
        revision: The REVISION string from a KANON_SOURCE_<name>_REVISION
            environment variable (e.g. ``main``, ``>=1.0.0``, ``a3b4c5...``).

    Returns:
        A :class:`RevisionShape` member describing the revision kind.
    """
    # SHA check: exactly 40 or 64 hex characters
    hex_chars = frozenset("0123456789abcdefABCDEF")
    if len(revision) in (SHA1_HEX_LENGTH, SHA256_HEX_LENGTH) and all(c in hex_chars for c in revision):
        return RevisionShape.SHA

    # Tag check: PEP 440 constraint or explicit refs/tags/ prefix
    if is_version_constraint(revision) or revision.startswith("refs/tags/"):
        return RevisionShape.TAG

    # Default: branch-pinned
    return RevisionShape.BRANCH


def _truncate_sha(sha: str) -> str:
    """Return the first ``BRANCH_SHA_TRUNCATION_LENGTH`` characters of a SHA.

    This matches the ``git`` default short-SHA convention. Used for the
    ``current``, ``latest-matching-spec``, and ``latest-available`` columns
    for branch-pinned and SHA-pinned sources in 'kanon outdated'.

    Args:
        sha: A full hexadecimal commit SHA (typically 40 or 64 characters,
            but any non-empty string is accepted; the first
            ``BRANCH_SHA_TRUNCATION_LENGTH`` characters are returned).

    Returns:
        The leading ``BRANCH_SHA_TRUNCATION_LENGTH`` characters of ``sha``.
    """
    return sha[:BRANCH_SHA_TRUNCATION_LENGTH]


def _list_branch_head(url: str, branch: str) -> str:
    """Return the full commit SHA at the HEAD of a remote branch.

    Runs ``git ls-remote <url> refs/heads/<branch>`` and parses the SHA from
    the single matching output line.

    Issues a single ``git ls-remote`` call with no timeout or retry logic.
    The caller is responsible for any retry or timeout policy if needed.

    Args:
        url: Git repository URL (any scheme accepted by git ls-remote).
        branch: Branch name without the ``refs/heads/`` prefix.

    Returns:
        The full 40-character hexadecimal commit SHA at the branch HEAD.

    Raises:
        RuntimeError: If the ``git`` binary is not found on PATH, or if the
            git command exits with a non-zero return code.
        ValueError: If the branch ref is not found in the remote's output
            (i.e., the branch does not exist on the remote).
    """
    ref = f"refs/heads/{branch}"
    try:
        result = subprocess.run(
            ["git", "ls-remote", url, ref],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ERROR: git binary not found. Install git and ensure it is on PATH.") from exc

    if result.returncode != 0:
        raise RuntimeError(f"ERROR: git ls-remote failed for {url!r}: {result.stderr.strip()}")

    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1] == ref:
            return parts[0]

    raise ValueError(
        f"ERROR: Branch '{branch}' ({ref}) not found on remote {url!r}.\n"
        f"Check that the branch name is correct and that the remote is accessible."
    )


def _resolve_symref_default_branch(url: str) -> str | None:
    """Resolve the default branch advertised by a remote's HEAD symref.

    Runs ``git ls-remote --symref <url> HEAD`` through the shared
    :func:`kanon_cli.core.git_runner.run_git_ls_remote` runner (so the retry and
    ``KANON_GIT_LS_REMOTE_TIMEOUT`` policy are not duplicated, spec Section 3 /
    FR-27) and parses the advertised symref line of the form::

        ref: refs/heads/<branch>\\tHEAD

    The ``<branch>`` component is returned (the ``refs/heads/`` prefix stripped).

    Args:
        url: Git repository URL (any scheme accepted by ``git ls-remote``).

    Returns:
        The bare default-branch name advertised by the remote HEAD symref, or
        ``None`` when the remote advertises no ``ref: refs/heads/...`` symref
        line (the caller fails fast with the actionable symref-absent error).

    Raises:
        RuntimeError: If ``git ls-remote --symref`` exits with a non-zero return
            code; the message names the URL and the git stderr.
    """
    returncode, stdout, stderr = run_git_ls_remote(
        ["git", "ls-remote", "--symref", url, "HEAD"],
        timeout=KANON_GIT_LS_REMOTE_TIMEOUT,
        retry_count=1,
    )
    if returncode != 0:
        raise RuntimeError(f"ERROR: git ls-remote --symref failed for {url!r}: {stderr.strip()}")

    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith(SYMREF_LINE_PREFIX):
            continue
        # Line shape: "ref: refs/heads/<branch>\tHEAD". Drop the "ref: " token,
        # then split off the trailing "\tHEAD" symref-name column.
        symref_target = stripped[len(SYMREF_LINE_PREFIX) :].split("\t", 1)[0].strip()
        if symref_target.startswith(SYMREF_HEADS_PREFIX):
            return symref_target[len(SYMREF_HEADS_PREFIX) :]

    return None


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
