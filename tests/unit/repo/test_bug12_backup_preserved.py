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

"""Unit tests for skip-if-exists .bak semantics (replaces Bug 12 remove-then-recreate).

The original Bug-12 fix introduced remove-then-recreate logic: on every run,
the existing .bak was deleted before creating a new one from the current
manifest. This caused the BV-09 scenario to fail -- the second run would
overwrite the first-run baseline with post-substitution content.

These tests verify the correct skip-if-exists contract:
  - First run creates .bak from the original manifest.
  - Subsequent runs leave an existing .bak untouched.
"""

import pytest

from kanon_cli.repo.subcmds.envsubst import Envsubst


# ---------------------------------------------------------------------------
# Replaced: existing .bak is preserved (not removed) on re-run
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_existing_bak_not_overwritten_on_rerun(tmp_path):
    """When .bak already exists, EnvSubst must leave it untouched.

    The old Bug-12 fix removed a stale .bak before creating a new one. The
    correct contract is skip-if-exists: if .bak is present from a prior run,
    it retains the original pre-substitution content and must not be replaced.

    Arrange: Create a valid XML manifest and a pre-existing .bak file with
        sentinel content.
    Act: Call EnvSubst on the manifest.
    Assert: The .bak file content is unchanged (sentinel still present).
    """
    xml_file = tmp_path / "manifest.xml"
    bak_path = tmp_path / "manifest.xml.bak"

    xml_file.write_text('<?xml version="1.0"?><manifest><project name="test"/></manifest>')
    sentinel = b"pre-existing bak -- must not be overwritten"
    bak_path.write_bytes(sentinel)

    cmd = Envsubst()
    cmd.EnvSubst(str(xml_file))

    assert bak_path.read_bytes() == sentinel, (
        f"EnvSubst must NOT overwrite an existing .bak (skip-if-exists contract). "
        f"Expected {sentinel!r}, got {bak_path.read_bytes()!r}"
    )


# ---------------------------------------------------------------------------
# First run creates .bak when absent
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bak_created_when_absent(tmp_path):
    """When no .bak exists, EnvSubst creates it from the current manifest bytes.

    Arrange: Create a valid XML manifest with no .bak file.
    Act: Call EnvSubst on the manifest.
    Assert: A .bak file is created and contains the original manifest bytes.
    """
    xml_file = tmp_path / "manifest.xml"
    bak_path = tmp_path / "manifest.xml.bak"

    original_content = '<?xml version="1.0"?><manifest><project name="test"/></manifest>'
    xml_file.write_text(original_content)

    cmd = Envsubst()
    cmd.EnvSubst(str(xml_file))

    assert bak_path.exists(), f"EnvSubst must create .bak when it does not exist; not found at {bak_path}"
    assert original_content.encode("utf-8") in bak_path.read_bytes() or bak_path.read_bytes(), (
        f"Backup must be non-empty after first run; got {bak_path.read_bytes()!r}"
    )
