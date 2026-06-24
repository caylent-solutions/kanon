"""Validate marketplace XML manifest files.

Checks:
  - All <linkfile dest> attributes use the ${CLAUDE_MARKETPLACES_DIR}
    variable prefix, rejecting hard-coded or relative paths.
  - All <include> chains are unbroken (every referenced file exists).
  - All flattened project path names are unique across manifests.
  - All <project revision> attributes follow valid formats.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from kanon_cli.constants import (
    ALLOWED_BRANCHES,
    MARKETPLACE_DIR_PREFIX,
    REVISION_REF_PREFIX_TAGS,
    REVISION_WILDCARD,
)
from kanon_cli.core.metadata import find_catalog_entry_files
from kanon_cli.version import is_pep440_version


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


def _is_pep440_constraint(component: str) -> bool:
    """Return True if *component* is a valid PEP 440 version constraint set.

    A single token (e.g. ``~=1.2.0``, ``>=1.0.0``) or a comma-separated
    compound set (e.g. ``>=1.0.0,<2.0.0``) is accepted when it parses cleanly
    via :class:`packaging.specifiers.SpecifierSet`. ``SpecifierSet`` is the same
    constraint grammar the resolver in ``kanon_cli.version`` uses, so the
    accepted constraint operands are full PEP 440 (no ``\\d+\\.\\d+\\.\\d+``
    floor) and the grammar is defined once (DRY).

    A bare token with no operator (e.g. ``1.0.0``) is rejected here because
    ``SpecifierSet`` does not accept an operatorless version; bare versions are
    validated as PEP 440 releases by :func:`is_pep440_version` on the
    tag-trailing-component path instead.

    Args:
        component: A single revision token (already split off any tag prefix).

    Returns:
        True if *component* parses as a non-empty ``SpecifierSet``; False on
        ``InvalidSpecifier`` or an empty specifier set.
    """
    try:
        specifier = SpecifierSet(component)
    except InvalidSpecifier:
        return False
    return len(specifier) > 0


def _is_valid_version_component(component: str) -> bool:
    """Return True if a tag-trailing component is a valid version token.

    The trailing component of a ``refs/tags/<path>/<component>`` tag (and a
    bare top-level revision) is valid when it is the wildcard, a full PEP 440
    version, or a PEP 440 constraint set:

    - the wildcard ``*`` (resolves to the highest available tag),
    - a canonical PEP 440 version (e.g. ``1``, ``1.2``, ``1.2.0a1``,
      ``1.0.0rc1``, ``2024.6``) accepted via :func:`is_pep440_version`, or
    - a PEP 440 version constraint set (e.g. ``~=1.2.0``, ``>=1.0.0,<2.0.0``)
      accepted via :func:`_is_pep440_constraint`.

    Args:
        component: A single revision token with no tag prefix and no ``/``.

    Returns:
        True if *component* is the wildcard, a PEP 440 version, or a PEP 440
        constraint set; False otherwise.
    """
    if component == REVISION_WILDCARD:
        return True
    if is_pep440_version(component):
        return True
    return _is_pep440_constraint(component)


def _is_valid_revision(revision: str) -> bool:
    """Check if a revision string is a valid format.

    The version grammar is full PEP 440 (no ``\\d+\\.\\d+\\.\\d+`` SemVer
    floor): the trailing component is parsed by the same
    ``packaging.version.Version`` / ``packaging.specifiers.SpecifierSet`` path
    the resolver in ``kanon_cli.version`` uses (DRY), so 1-/2-part releases,
    pre-releases, release candidates, and calendar versions are all accepted.

    Valid formats:
    - refs/tags/<path>/<pep440> (e.g., refs/tags/example/proj/1.0.0,
      refs/tags/example/proj/1.2.0a1, refs/tags/example/proj/2024.6)
    - refs/tags/<path>/<constraint> (e.g., refs/tags/example/proj/~=1.0.0)
    - refs/tags/<path>/* (wildcard trailing component)
    - Single version constraints (~=1.2.0, >=1.0.0, <2.0.0)
    - Compound version constraints (>=1.0.0,<2.0.0)
    - Wildcard (*)
    - Branch names (main)

    The trailing version component is split on the last ``/`` and validated as
    canonical PEP 440; the prefix path before it is not constrained beyond
    being non-empty.

    Args:
        revision: The ``revision`` attribute value of a manifest ``<project>``.

    Returns:
        True if *revision* matches one of the valid formats above.
    """
    if revision in ALLOWED_BRANCHES:
        return True
    if revision == REVISION_WILDCARD:
        return True
    # refs/tags/<path>/<trailing>: split on the last '/' and validate the
    # trailing component as a PEP 440 version, constraint set, or wildcard.
    # The path between the prefix and the trailing component must be non-empty.
    if revision.startswith(REVISION_REF_PREFIX_TAGS) and "/" in revision[len(REVISION_REF_PREFIX_TAGS) :]:
        last_component = revision.rsplit("/", 1)[-1]
        return _is_valid_version_component(last_component)
    # Bare top-level revision (no tag prefix): a PEP 440 constraint set or the
    # wildcard. A bare PEP 440 version with no operator is intentionally not
    # accepted here as a top-level revision; pin it with the refs/tags/ prefix.
    return _is_pep440_constraint(revision)


def validate_tag_format(xml_files: list[Path]) -> list[str]:
    """Validate that all project revision attributes follow valid formats.

    Checks that each <project> element's revision attribute is either a
    refs/tags/<path>/<pep440> tag (full PEP 440 trailing component, no
    \\d+\\.\\d+\\.\\d+ floor), a PEP 440 version constraint, a wildcard, or
    an allowed branch name. Returns errors for any invalid revisions.

    Args:
        xml_files: List of paths to marketplace XML manifest files.

    Returns:
        List of error messages. Empty if all revisions are valid.
        Each error identifies the file, project name, and invalid revision.
    """
    errors: list[str] = []

    for xml_file in xml_files:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        for project in root.findall("project"):
            revision = project.get("revision", "")
            if revision and not _is_valid_revision(revision):
                project_name = project.get("name", "<unknown>")
                errors.append(
                    f"{xml_file}: project '{project_name}' has "
                    f"invalid revision='{revision}' -- must be "
                    f"refs/tags/<path>/<pep440>, a PEP 440 version constraint, "
                    f"a wildcard, or an allowed branch"
                )

    return errors


def validate_marketplace(repo_root: Path) -> int:
    """Validate all marketplace XML files found under repo-specs/.

    Scans for *-marketplace.xml files and validates each one
    for linkfile dest attributes and include chain integrity.
    Exits with non-zero code if any validation errors are found.

    Args:
        repo_root: Repository root directory.

    Returns:
        0 if all files pass validation, 1 otherwise.
    """
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
    all_errors.extend(validate_tag_format(marketplace_files))

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
