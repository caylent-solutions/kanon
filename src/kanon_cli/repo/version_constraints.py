# Copyright (C) 2024 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""PEP 440 version constraint detection and resolution.

Provides functions to detect PEP 440 constraint syntax in revision strings
and resolve constraints against available tags to find the highest matching
version.

Spec references:
- Section 5.5: PEP 440 constraint syntax table, supported types, resolution.
- Section 17.2: Function signatures for is_version_constraint and
  resolve_version_constraint.
"""

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

import error

# PEP 440 constraint operators that can appear at the start of a version
# specifier. Order matters: two-character operators must be checked before
# single-character operators to avoid partial matches.
_PEP440_OPERATORS = ("~=", ">=", "<=", "!=", "==", ">", "<")


def is_version_constraint(revision):
    """Detect PEP 440 constraint syntax in the last path component.

    Examines the last path component of a revision string and returns True
    when it contains PEP 440 constraint operators (~=, >=, <, <=, >, !=,
    ==, *) or range syntax (multiple specifiers joined by comma).

    Args:
        revision: A revision string, possibly containing path separators.
            Example: "refs/tags/dev/python/quality-agent/~=1.2.0"

    Returns:
        True if the last path component contains PEP 440 constraint syntax,
        False otherwise.
    """
    last_component = revision.rsplit("/", 1)[-1]

    # Wildcard is a constraint.
    if last_component == "*":
        return True

    # Check for PEP 440 operators.
    for op in _PEP440_OPERATORS:
        if last_component.startswith(op):
            return True

    # Range constraints contain commas with operators (e.g., ">=1.0.0,<2.0.0").
    if "," in last_component:
        parts = last_component.split(",")
        return any(part.lstrip().startswith(op) for part in parts for op in _PEP440_OPERATORS)

    return False


def resolve_version_constraint(revision, available_tags):
    """Resolve a PEP 440 version constraint to the highest matching tag.

    Splits the revision into a prefix and constraint, filters available tags
    by the prefix, parses version suffixes with packaging.version.Version,
    evaluates the constraint with packaging.specifiers.SpecifierSet, and
    returns the full tag name of the highest matching version.

    Args:
        revision: A revision string with a PEP 440 constraint in the last
            path component.
            Example: "refs/tags/dev/python/quality-agent/~=1.2.0"
        available_tags: List of tag strings to match against.
            Example: ["refs/tags/dev/python/quality-agent/1.0.0", ...]

    Returns:
        The full tag name of the highest version that satisfies the
        constraint.

    Raises:
        error.ManifestInvalidRevisionError: If no available tag matches
            the constraint.
    """
    # Split revision into prefix and constraint at the last '/'.
    prefix, constraint_str = revision.rsplit("/", 1)

    # Build the specifier. Wildcard matches all versions.
    if constraint_str == "*":
        specifier = SpecifierSet()
    else:
        try:
            specifier = SpecifierSet(constraint_str)
        except InvalidSpecifier:
            raise error.ManifestInvalidRevisionError(f"invalid version constraint: {constraint_str}")

    # Filter tags by prefix and parse their version suffixes.
    tag_prefix = prefix + "/"
    candidates = []
    for tag in available_tags:
        if not tag.startswith(tag_prefix):
            continue
        version_str = tag[len(tag_prefix) :]
        try:
            version = Version(version_str)
        except InvalidVersion:
            continue
        if version in specifier:
            candidates.append((version, tag))

    if not candidates:
        raise error.ManifestInvalidRevisionError(f"no tags match constraint '{constraint_str}' under '{prefix}'")

    # Return the tag with the highest matching version.
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1][1]
