# Copyright (C) 2026 Caylent, Inc.
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

"""Unit tests for Bug 15: Pre-release version constraint docs.

Bug reference: specs/BACKLOG-repo-bugs.md Bug 15 -- Pre-release versions
silently excluded by PEP 440. The help text must include a note explaining
that pre-release version constraints follow semantic versioning rules and
may behave differently from release constraints.
"""

import pytest

from kanon_cli.repo import version_constraints


# ---------------------------------------------------------------------------
# AC-TEST-009 -- Pre-release note present in help text / module docstring
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_prerelease_note_present_in_module_docstring():
    """AC-TEST-009: Pre-release note is present in version_constraints module.

    The version_constraints module must document the pre-release exclusion
    behavior in its module-level docstring. Users relying on PEP 440
    constraints must understand that pre-release versions (1.0.0a1, 1.0.0b2,
    etc.) are excluded by non-pre-release constraint specifiers by default.

    Arrange: Import the version_constraints module.
    Act: Access its __doc__ attribute.
    Assert: The module docstring contains a note about pre-release version
    behavior (e.g., 'pre-release' or 'pre_release' or 'prerelease').
    """
    module_doc = version_constraints.__doc__ or ""
    assert "pre-release" in module_doc.lower() or "prerelease" in module_doc.lower(), (
        "Expected version_constraints module docstring to mention 'pre-release' "
        "or 'prerelease', but it does not. "
        f"Current docstring: {module_doc!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-010 -- Help text mentions semantic versioning
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_help_text_mentions_semantic_versioning():
    """AC-TEST-010: Help text mentions semantic versioning rules.

    The version_constraints module documentation must reference semantic
    versioning (or PEP 440 spec) in the context of pre-release behavior.
    This ensures users understand that the constraint evaluation follows
    defined versioning rules, not arbitrary filtering.

    Arrange: Import the version_constraints module.
    Act: Access its __doc__ attribute and the resolve_version_constraint
    function's docstring.
    Assert: At least one of these contains a reference to semantic
    versioning or PEP 440 in relation to pre-release behavior.
    """
    module_doc = version_constraints.__doc__ or ""
    resolve_doc = version_constraints.resolve_version_constraint.__doc__ or ""
    is_constraint_doc = version_constraints.is_version_constraint.__doc__ or ""

    combined = (module_doc + resolve_doc + is_constraint_doc).lower()

    has_pep440 = "pep 440" in combined or "pep440" in combined
    has_semver = "semantic versioning" in combined or "semver" in combined

    assert has_pep440 or has_semver, (
        "Expected version_constraints documentation to mention PEP 440 or semantic "
        "versioning in the context of pre-release handling. "
        f"Module doc: {module_doc!r}, "
        f"resolve_version_constraint doc: {resolve_doc!r}"
    )
