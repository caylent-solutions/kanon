"""Validate all XML manifest files in the repo-specs directory.

Checks:
  - Well-formed XML
  - Required attributes on <project> elements (name, path, remote, revision)
  - Required attributes on <remote> elements (name, fetch)
  - Valid <include> name attributes point to existing files
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def find_xml_files(root_dir: str) -> list[Path]:
    """Find all XML files under the given directory."""
    return sorted(Path(root_dir).rglob("*.xml"))


def validate_manifest(filepath: Path, repo_root: Path) -> list[str]:
    """Validate a single manifest XML file. Returns list of error messages."""
    errors = []

    try:
        tree = ET.parse(filepath)
    except ET.ParseError as e:
        return [f"{filepath}: XML parse error: {e}"]

    root = tree.getroot()
    if root.tag != "manifest":
        errors.append(f"{filepath}: Root element must be <manifest>, got <{root.tag}>")
        return errors

    for project in root.findall("project"):
        for attr in ("name", "path", "remote", "revision"):
            if not project.get(attr):
                errors.append(f"{filepath}: <project> missing required attribute '{attr}'")

    for remote in root.findall("remote"):
        for attr in ("name", "fetch"):
            if not remote.get(attr):
                errors.append(f"{filepath}: <remote> missing required attribute '{attr}'")

    for include in root.findall("include"):
        name = include.get("name")
        if not name:
            errors.append(f"{filepath}: <include> missing required attribute 'name'")
        else:
            include_path = repo_root / name
            if not include_path.exists():
                errors.append(f'{filepath}: <include name="{name}"> references non-existent file: {include_path}')

    return errors


def validate_xml(repo_root: Path) -> int:
    """Validate all XML manifest files under repo-specs/.

    Args:
        repo_root: Repository root directory.

    Returns:
        0 if all files pass validation, 1 otherwise.
    """
    search_dirs = [
        repo_root / "repo-specs",
    ]

    xml_files = []
    for search_dir in search_dirs:
        if search_dir.exists():
            xml_files.extend(find_xml_files(search_dir))

    if not xml_files:
        print(
            "Error: No XML files found in repo-specs/",
            file=sys.stderr,
        )
        return 1

    all_errors = []
    for xml_file in xml_files:
        print(f"Validating {xml_file.relative_to(repo_root)}...")
        errors = validate_manifest(xml_file, repo_root)
        all_errors.extend(errors)

    if all_errors:
        print(f"\nFound {len(all_errors)} error(s):", file=sys.stderr)
        for error in all_errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"\nAll {len(xml_files)} manifest files are valid.")
    return 0
