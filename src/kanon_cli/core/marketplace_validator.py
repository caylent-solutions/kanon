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

from kanon_cli.constants import (
    ALLOWED_BRANCHES,
    CONSTRAINT_RE,
    MARKETPLACE_DIR_PREFIX,
    MARKETPLACE_FILE_GLOB,
    REFS_TAGS_RE,
)


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
                    f"invalid linkfile dest='{dest}' — "
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


def _is_valid_revision(revision: str) -> bool:
    """Check if a revision string is a valid format.

    Valid formats:
    - refs/tags/<path>/<semver> (e.g., refs/tags/example/proj/1.0.0)
    - Single version constraints (~=1.2.0, >=1.0.0, <2.0.0)
    - Compound version constraints (>=1.0.0,<2.0.0)
    - Wildcard (*)
    - Branch names (main)
    """
    if revision in ALLOWED_BRANCHES:
        return True
    if revision == "*":
        return True
    if REFS_TAGS_RE.match(revision):
        return True
    # Support compound constraints separated by commas (e.g., >=1.0.0,<2.0.0)
    parts = revision.split(",")
    if all(CONSTRAINT_RE.match(part) for part in parts):
        return True
    return False


def validate_tag_format(xml_files: list[Path]) -> list[str]:
    """Validate that all project revision attributes follow valid formats.

    Checks that each <project> element's revision attribute is either a
    refs/tags/<path>/<semver> tag, a version constraint, a wildcard, or
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
                    f"invalid revision='{revision}' — must be "
                    f"refs/tags/<path>/<semver>, a version constraint, "
                    f"or an allowed branch"
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
    marketplace_files = sorted(repo_root.joinpath("repo-specs").rglob(MARKETPLACE_FILE_GLOB))

    if not marketplace_files:
        print(
            "Error: No *-marketplace.xml files found under repo-specs/",
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
