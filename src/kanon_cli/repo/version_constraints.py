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

Thin wrapper delegating all version constraint logic to ``kanon_cli.version``,
which is the canonical implementation. This module preserves the function
signatures required by the repo module (``is_version_constraint``,
``resolve_version_constraint``) while eliminating duplicate logic.

Pre-release version behavior:
    By default, PEP 440 constraint specifiers (such as >=1.0.0 or ~=2.0.0)
    exclude pre-release versions (e.g., 1.0.0a1, 1.0.0b2, 1.0.0rc1) unless
    the constraint itself references a pre-release version. This follows the
    semantic versioning rules defined in PEP 440. For example, >=1.0.0 will
    not match 1.0.0a1 even though 1.0.0a1 is technically "before" 1.0.0.
    To include pre-release versions, specify a pre-release constraint
    explicitly (e.g., >=1.0.0a1).

Spec references:
- Section 5.5: PEP 440 constraint syntax table, supported types, resolution.
- Section 17.2: Function signatures for is_version_constraint and
  resolve_version_constraint.
"""

from kanon_cli import version as kanon_version

from . import error


def is_version_constraint(revision):
    """Detect PEP 440 constraint syntax in the last path component.

    Delegates to ``kanon_cli.version.is_version_constraint``.

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
    return kanon_version.is_version_constraint(revision)


def resolve_version_constraint(revision, available_tags):
    """Resolve a PEP 440 version constraint to the highest matching tag.

    Delegates to ``kanon_cli.version._resolve_constraint_from_tags``,
    converting ``ValueError`` to ``error.ManifestInvalidRevisionError``.

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
    try:
        return kanon_version._resolve_constraint_from_tags(revision, available_tags)
    except ValueError as exc:
        raise error.ManifestInvalidRevisionError(str(exc)) from exc
