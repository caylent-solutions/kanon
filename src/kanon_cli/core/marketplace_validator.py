"""Validate marketplace XML manifest files.

Checks:
  - All <linkfile dest> attributes use the ${CLAUDE_MARKETPLACES_DIR}
    variable prefix, rejecting hard-coded or relative paths.
  - All <include> chains are unbroken (every referenced file exists).
  - All flattened project path names are unique across manifests.
  - All <project revision> attributes are exact existing git tags
    (refs/tags/<deep/path>/<pep440>): exact-only, no branch, no wildcard,
    no version-range constraint (spec Section 4.5 / Section 6 / FR-22).
  - Every <project revision> -- including a revision a <project> inherits from
    the manifest's <default revision> -- is existence-checked against the
    project's resolved remote via git ls-remote (two-tier: a local/file://
    repo resolves offline; a remote repo degrades to format-only with a warning
    when the host is offline, unless the CI/gate flag makes existence mandatory).
"""

import os
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

from kanon_cli.constants import (
    GIT_RETRY_COUNT_DEFAULT,
    GIT_RETRY_COUNT_ENV_VAR,
    KANON_GIT_LS_REMOTE_TIMEOUT,
    MARKETPLACE_DIR_PREFIX,
    REVISION_EXISTENCE_REQUIRED_ENV_VAR,
    REVISION_REF_PREFIX_TAGS,
)
from kanon_cli.core.git_runner import run_git_ls_remote
from kanon_cli.core.manifest import walk_includes_collecting_remotes
from kanon_cli.core.metadata import find_catalog_entry_files
from kanon_cli.version import is_pep440_version

# Type of the injectable ls-remote runner used by the existence check. The
# default implementation (:func:`_default_ls_remote`) shells the shared
# ``run_git_ls_remote`` runner from E1; tests inject a stub so they never touch
# the network. The callable receives (url, ref) and returns the git ls-remote
# (returncode, stdout, stderr) tuple.
LsRemoteRunner = Callable[[str, str], tuple[int, str, str]]


def validate_linkfile_dest(xml_path: Path) -> list[str]:
    """Validate all linkfile dest attributes in a manifest XML file.

    Checks that every <linkfile> element's dest attribute starts with
    ${CLAUDE_MARKETPLACES_DIR}/. Returns a list of error messages for
    any violations found. An empty list means validation passed.

    Args:
        xml_path: Path to the XML manifest file to validate.

    Returns:
        List of error messages. Empty if all dest attributes are valid.
        Each error identifies the file, project name, and invalid dest.
    """
    errors: list[str] = []
    tree = ET.parse(xml_path)
    root = tree.getroot()

    for project in root.findall("project"):
        project_name = project.get("name", "<unknown>")
        for linkfile in project.findall("linkfile"):
            dest = linkfile.get("dest", "")
            if not dest.startswith(MARKETPLACE_DIR_PREFIX):
                errors.append(
                    f"{xml_path}: project '{project_name}' has "
                    f"invalid linkfile dest='{dest}' -- "
                    f"must start with {MARKETPLACE_DIR_PREFIX}"
                )

    return errors


def validate_include_chain(
    xml_path: Path,
    repo_root: Path,
) -> list[str]:
    """Validate that all includes in a manifest chain resolve to files.

    Recursively follows <include> elements starting from xml_path,
    checking that each referenced file exists. Returns errors for any
    broken links in the chain.

    Args:
        xml_path: Path to the XML manifest file to validate.
        repo_root: Repository root for resolving include paths.

    Returns:
        List of error messages. Empty if the entire chain is valid.
        Each error identifies the source file and missing include.
    """
    errors: list[str] = []
    visited: set[str] = set()

    def _walk(current_path: Path) -> None:
        resolved = str(current_path.resolve())
        if resolved in visited:
            return
        visited.add(resolved)

        try:
            tree = ET.parse(current_path)
        except ET.ParseError as exc:
            errors.append(f"{current_path}: XML parse error: {exc}")
            return
        root = tree.getroot()

        for include in root.findall("include"):
            name = include.get("name")
            if not name:
                errors.append(f'{current_path}: <include> element missing required "name" attribute')
                continue
            include_path = repo_root / name
            if not include_path.exists():
                errors.append(f'{current_path}: <include name="{name}"> references non-existent file: {include_path}')
            else:
                _walk(include_path)

    _walk(xml_path)
    return errors


def validate_name_uniqueness(xml_files: list[Path]) -> list[str]:
    """Validate that all project path attributes are unique across manifests.

    Parses each XML file, collects all <project path="..."> values, and
    reports any duplicates along with the files containing them.

    Args:
        xml_files: List of paths to marketplace XML manifest files.

    Returns:
        List of error messages. Empty if all paths are unique.
        Each error identifies the duplicate path and conflicting files.
    """
    errors: list[str] = []
    path_to_files: dict[str, list[str]] = {}

    for xml_file in xml_files:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        for project in root.findall("project"):
            path_attr = project.get("path", "")
            if path_attr:
                if path_attr not in path_to_files:
                    path_to_files[path_attr] = []
                path_to_files[path_attr].append(str(xml_file))

    for path_attr, files in path_to_files.items():
        if len(files) > 1:
            file_list = ", ".join(files)
            errors.append(f"Duplicate project path '{path_attr}' found in: {file_list}")

    return errors


def _is_exact_tag_revision(revision: str) -> bool:
    """Return True if *revision* is an exact-tag ``<project revision>``.

    The exact-only revision grammar (spec Section 4.5 / Section 6 / FR-22) is:

        refs/tags/<deep/path>/<pep440>

    where ``<pep440>`` is a single, canonical PEP 440 version token validated
    by the shared :func:`kanon_cli.version.is_pep440_version` grammar (the same
    full-PEP-440 grammar the resolver uses -- E7-F1-S1, DRY). The trailing
    component is split off the last ``/``; the path between the
    ``refs/tags/`` prefix and that component must be non-empty.

    Exact-only means a branch (e.g. ``main``), the wildcard ``*``, and a
    single or compound version-range constraint (e.g. ``>=0.1.0,<1.0.0``) are
    all REJECTED: only a concrete existing-tag shape is accepted, so no project
    is pinned to a moving target.

    Args:
        revision: The ``revision`` attribute value of a manifest ``<project>``
            (or the inherited ``<default revision>``).

    Returns:
        True only when *revision* is a ``refs/tags/<deep/path>/<pep440>`` exact
        tag; False for branches, the wildcard, constraints, and any other shape.
    """
    if not revision.startswith(REVISION_REF_PREFIX_TAGS):
        return False
    remainder = revision[len(REVISION_REF_PREFIX_TAGS) :]
    # Require a non-empty path before the trailing version component so the
    # single trailing-component split is well-defined (refs/tags/<path>/<ver>).
    if "/" not in remainder:
        return False
    path_part, _, last_component = remainder.rpartition("/")
    if not path_part:
        return False
    return is_pep440_version(last_component)


_INVALID_REVISION_HINT = (
    "must be an exact tag refs/tags/<path>/<pep440> "
    "(exact-only: no branch, no '*' wildcard, no version-range constraint)"
)


def _resolve_default_revision(xml_file: Path, repo_root: Path) -> str | None:
    """Return the ``<default revision>`` reachable from *xml_file*, if any.

    Walks the manifest's ``<include>`` chain (depth-first, cycle-safe) looking
    for a ``<default revision="...">`` element. A ``<project>`` that omits its
    own ``revision`` attribute inherits this value (the repo-tool manifest
    convention), so it must be validated against the same exact-tag rule -- this
    is the ``remote.xml`` ``<default revision>`` inheritance leg (spec Section
    4.5 / FR-42): no project silently inherits a branch revision.

    Args:
        xml_file: The marketplace manifest file being validated.
        repo_root: Repository root used to resolve ``<include>`` paths.

    Returns:
        The first ``<default revision>`` value found in the include chain, or
        None when no ``<default>`` element declares a revision.
    """
    visited: set[str] = set()

    def _walk(current: Path) -> str | None:
        resolved = str(current.resolve())
        if resolved in visited:
            return None
        visited.add(resolved)
        try:
            tree = ET.parse(current)
        except ET.ParseError:
            return None
        root = tree.getroot()
        for default_el in root.findall("default"):
            revision = default_el.get("revision")
            if revision:
                return revision
        for include in root.findall("include"):
            name = include.get("name")
            if not name:
                continue
            include_path = repo_root / name
            if include_path.exists():
                found = _walk(include_path)
                if found is not None:
                    return found
        return None

    return _walk(xml_file)


def _iter_project_revisions(
    xml_file: Path,
    repo_root: Path,
) -> list[tuple[str, str, bool]]:
    """Yield the effective ``(project_name, revision, inherited)`` triples.

    For every ``<project>`` in *xml_file*, resolves its effective revision: its
    own ``revision`` attribute when present, otherwise the ``<default revision>``
    inherited from the include chain. Projects that declare no revision and
    inherit no default are skipped (there is nothing to validate).

    Args:
        xml_file: The marketplace manifest file being validated.
        repo_root: Repository root used to resolve include paths for the
            ``<default revision>`` lookup.

    Returns:
        A list of ``(project_name, effective_revision, inherited)`` triples,
        where ``inherited`` is True when the revision came from the manifest's
        ``<default revision>`` rather than the project's own attribute.
    """
    tree = ET.parse(xml_file)
    root = tree.getroot()

    default_revision: str | None = None
    default_resolved = False

    triples: list[tuple[str, str, bool]] = []
    for project in root.findall("project"):
        project_name = project.get("name", "<unknown>")
        own_revision = project.get("revision", "")
        if own_revision:
            triples.append((project_name, own_revision, False))
            continue
        # Resolve the inherited <default revision> lazily and only once.
        if not default_resolved:
            default_revision = _resolve_default_revision(xml_file, repo_root)
            default_resolved = True
        if default_revision:
            triples.append((project_name, default_revision, True))
    return triples


def validate_tag_format(xml_files: list[Path], repo_root: Path) -> list[str]:
    """Validate that every effective ``<project revision>`` is an exact tag.

    Checks each ``<project>`` element's effective revision -- its own
    ``revision`` attribute, or the ``<default revision>`` it inherits when the
    attribute is omitted -- against the exact-only rule
    (:func:`_is_exact_tag_revision`). A branch, the wildcard, and a single or
    compound version-range constraint are all rejected with an actionable
    exact-tag error (spec Section 4.5 / Section 6 / FR-22).

    Args:
        xml_files: List of paths to marketplace XML manifest files.
        repo_root: Repository root used to resolve ``<default revision>``
            inheritance through the include chain.

    Returns:
        List of error messages. Empty if all revisions are exact tags.
        Each error identifies the file, project name, and invalid revision.
    """
    errors: list[str] = []

    for xml_file in xml_files:
        for project_name, revision, inherited in _iter_project_revisions(xml_file, repo_root):
            if _is_exact_tag_revision(revision):
                continue
            source = "inherited <default revision>" if inherited else "revision"
            errors.append(
                f"{xml_file}: project '{project_name}' has invalid {source}='{revision}' -- {_INVALID_REVISION_HINT}"
            )

    return errors


def _default_ls_remote(url: str, ref: str) -> tuple[int, str, str]:
    """Run ``git ls-remote <url> <ref>`` through the shared E1 runner.

    Routes the existence-check ls-remote call through
    :func:`kanon_cli.core.git_runner.run_git_ls_remote` so the retry policy and
    the ``KANON_GIT_LS_REMOTE_TIMEOUT`` per-attempt timeout are not duplicated
    (spec Section 3 / FR-27). The retry count comes from
    ``KANON_GIT_RETRY_COUNT`` (default :data:`GIT_RETRY_COUNT_DEFAULT`); the
    timeout from :data:`KANON_GIT_LS_REMOTE_TIMEOUT`. No value is hard-coded.

    Args:
        url: The git remote URL (or local/file:// repo path) to query.
        ref: The exact ref to look up (a ``refs/tags/<path>/<pep440>`` value).

    Returns:
        The ``(returncode, stdout, stderr)`` tuple from the final attempt.
    """
    retry_count = _env_int(GIT_RETRY_COUNT_ENV_VAR, GIT_RETRY_COUNT_DEFAULT)
    return run_git_ls_remote(["git", "ls-remote", url, ref], KANON_GIT_LS_REMOTE_TIMEOUT, retry_count)


def _env_int(var: str, default: int) -> int:
    """Return the integer value of environment variable *var* or *default*.

    Mirrors the guarded ``_env_int`` helper in ``constants.py`` for the one
    retry-count read this module performs, failing fast on a non-integer value
    rather than silently falling back.

    Args:
        var: Environment variable name.
        default: Default integer when the variable is unset.

    Returns:
        The parsed integer.

    Raises:
        SystemExit: When the variable is set to a non-integer value.
    """
    raw = os.environ.get(var)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"ERROR: {var} must be an integer; got {raw!r}")


def _is_local_source(url: str) -> bool:
    """Return True when *url* names a local/file:// repo (offline-resolvable).

    A local source -- a ``file://`` URL or a bare filesystem path (no scheme
    and no SSH ``host:path`` shorthand) -- is existence-checkable offline, so
    its existence check is always mandatory (never degraded). A remote source
    (https://, ssh://, git@host:...) requires network access and degrades to
    format-only when the host is unreachable.

    Args:
        url: The resolved fetch URL for the project's remote.

    Returns:
        True for a ``file://`` URL or a local filesystem path; False for a
        network remote.
    """
    if url.startswith("file://"):
        return True
    if "://" in url:
        return False
    # An SSH shorthand (git@host:org/repo or host:org/repo) is a network remote.
    # A leading '/' or '.' (absolute or relative path) is local; a 'host:path'
    # without a slash before the colon is SSH shorthand.
    if url.startswith(("/", ".", "~")):
        return True
    colon = url.find(":")
    slash = url.find("/")
    if colon != -1 and (slash == -1 or colon < slash):
        # 'host:path' shorthand -- a network SSH remote.
        return False
    return True


def _resolve_project_remote_urls(
    xml_file: Path,
    repo_root: Path,
    env: dict[str, str],
) -> dict[str, str]:
    """Return a ``project_name -> resolved fetch URL`` map for *xml_file*.

    Resolves each ``<project remote="X">`` to the fetch URL of the matching
    ``<remote name="X" fetch="...">`` definition reachable through the include
    chain, expanding ``${VAR}`` placeholders from *env*. Projects whose remote
    cannot be resolved are omitted (the unresolved-remote error is the remote-url
    audit check's responsibility, not the revision existence check's).

    Args:
        xml_file: The marketplace manifest file being validated.
        repo_root: Repository root used to resolve include paths.
        env: Environment dict used to expand ``${VAR}`` placeholders in fetch
            URLs.

    Returns:
        Mapping of project name to its expanded fetch URL.
    """
    try:
        remote_map = walk_includes_collecting_remotes(xml_file, repo_root)
    except (ET.ParseError, FileNotFoundError, OSError):
        return {}

    tree = ET.parse(xml_file)
    root = tree.getroot()
    resolved: dict[str, str] = {}
    for project in root.findall("project"):
        remote_attr = project.get("remote")
        if not remote_attr:
            continue
        fetch_url = remote_map.get(remote_attr)
        if not fetch_url:
            continue
        expanded = _expand_env(fetch_url, env)
        resolved[project.get("name", "<unknown>")] = expanded
    return resolved


def _expand_env(value: str, env: dict[str, str]) -> str:
    """Expand ``${VAR}`` placeholders in *value* using *env* (leave unknowns).

    Args:
        value: A fetch URL possibly containing ``${VAR}`` tokens.
        env: Environment dict to substitute from.

    Returns:
        The string with known placeholders substituted; unknown placeholders
        are left verbatim.
    """
    from string import Template

    return Template(value).safe_substitute(env)


def validate_revision_existence(
    xml_files: list[Path],
    repo_root: Path,
    env: dict[str, str],
    ls_remote: LsRemoteRunner,
) -> list[str]:
    """Existence-check every exact-tag ``<project revision>`` against its remote.

    For each ``<project>`` whose effective revision is an exact tag, resolves the
    project's remote fetch URL and runs ``git ls-remote <url> <revision>`` through
    *ls_remote*. Two-tier + local-aware semantics (spec Section 4.5):

    - A local/``file://`` source resolves offline: a missing tag is always a hard
      ERROR (the repo is reachable without the network).
    - A remote source that is reachable: a missing tag is a hard ERROR.
    - A remote source that is unreachable/offline: existence degrades to
      format-only with a WARN, UNLESS the CI/gate flag
      ``KANON_VALIDATE_REQUIRE_EXISTENCE=1`` is set, in which case the
      unconfirmable existence is a hard ERROR (existence is mandatory).

    Revisions that are not exact tags are skipped here -- their format error is
    raised by :func:`validate_tag_format`; the existence check never double-reports
    a format failure. Projects with no resolvable remote are skipped (the
    unresolved-remote error belongs to the remote-url check).

    Args:
        xml_files: List of marketplace XML manifest paths.
        repo_root: Repository root used to resolve include paths and defaults.
        env: Environment dict for fetch-URL expansion and the CI/gate flag.
        ls_remote: Injectable ``(url, ref) -> (rc, stdout, stderr)`` runner.

    Returns:
        A list of ERROR strings (each prefixed-by-file). WARN lines are NOT
        returned here -- they are emitted to stderr by the caller -- so only hard
        existence failures contribute to the non-zero exit.
    """
    require_existence = env.get(REVISION_EXISTENCE_REQUIRED_ENV_VAR, "") == "1"
    errors: list[str] = []

    for xml_file in xml_files:
        remote_urls = _resolve_project_remote_urls(xml_file, repo_root, env)
        for project_name, revision, _inherited in _iter_project_revisions(xml_file, repo_root):
            if not _is_exact_tag_revision(revision):
                # Format failure already reported by validate_tag_format.
                continue
            url = remote_urls.get(project_name)
            if url is None:
                # Unresolvable remote -- the remote-url check owns that error.
                continue

            returncode, stdout, _stderr = ls_remote(url, revision)
            local = _is_local_source(url)

            if returncode == 0:
                if revision in stdout:
                    continue
                # Reachable remote/local repo, but the tag does not exist.
                errors.append(
                    f"{xml_file}: project '{project_name}' pins revision='{revision}' "
                    f"which does not exist on remote {url!r} "
                    f"(git ls-remote returned no matching ref). "
                    f"Pin an existing tag or create the tag in the source repository."
                )
                continue

            # Non-zero ls-remote: the remote is unreachable (or, for a local
            # source, the path is unusable). A local source must always resolve,
            # so a failure there is a hard error. A remote source degrades to
            # format-only with a WARN unless the CI/gate flag is set.
            if local or require_existence:
                errors.append(
                    f"{xml_file}: project '{project_name}' revision='{revision}' "
                    f"could not be existence-checked against {url!r} "
                    f"(git ls-remote exit {returncode}). "
                    f"Existence is mandatory ({'local source' if local else REVISION_EXISTENCE_REQUIRED_ENV_VAR + '=1'})."
                )
                continue

            print(
                f"WARNING: {xml_file}: project '{project_name}' revision='{revision}' "
                f"existence not verified -- remote {url!r} is unreachable "
                f"(git ls-remote exit {returncode}); validated format only. "
                f"Set {REVISION_EXISTENCE_REQUIRED_ENV_VAR}=1 to require existence.",
                file=sys.stderr,
            )

    return errors


def validate_marketplace(
    repo_root: Path,
    env: dict[str, str] | None = None,
    ls_remote: LsRemoteRunner | None = None,
) -> int:
    """Validate all marketplace XML files found under repo-specs/.

    Scans for catalog entry manifests (``*.xml`` with a ``<catalog-metadata>``
    block) and validates each one for linkfile dest attributes, include chain
    integrity, project path uniqueness, exact-only ``<project revision>`` tag
    format (covering revisions inherited from ``<default revision>``), and
    two-tier + local-aware revision existence. Exits with a non-zero code if any
    validation errors are found.

    Args:
        repo_root: Repository root directory.
        env: Environment dict for fetch-URL expansion and the CI/gate flag;
            defaults to ``os.environ`` when None.
        ls_remote: Injectable ls-remote runner for the existence check; defaults
            to the shared E1 runner when None.

    Returns:
        0 if all files pass validation, 1 otherwise.
    """
    effective_env: dict[str, str] = dict(os.environ) if env is None else env
    runner: LsRemoteRunner = _default_ls_remote if ls_remote is None else ls_remote

    marketplace_files = find_catalog_entry_files(repo_root)

    if not marketplace_files:
        print(
            "Error: No catalog entry manifests (*.xml with a <catalog-metadata> block) found under repo-specs/",
            file=sys.stderr,
        )
        return 1

    all_errors: list[str] = []
    for xml_file in marketplace_files:
        rel_path = xml_file.relative_to(repo_root)
        print(f"Validating {rel_path}...")
        all_errors.extend(validate_linkfile_dest(xml_file))
        all_errors.extend(validate_include_chain(xml_file, repo_root))

    all_errors.extend(validate_name_uniqueness(marketplace_files))
    all_errors.extend(validate_tag_format(marketplace_files, repo_root))
    all_errors.extend(validate_revision_existence(marketplace_files, repo_root, effective_env, runner))

    if all_errors:
        print(
            f"\nFound {len(all_errors)} validation error(s):",
            file=sys.stderr,
        )
        for error in all_errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"\nAll {len(marketplace_files)} marketplace files passed.")
    return 0
