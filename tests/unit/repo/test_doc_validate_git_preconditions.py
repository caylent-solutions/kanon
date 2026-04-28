# Copyright (C) 2026 The Android Open Source Project
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

"""Unit tests verifying git-precondition and stderr-capture doc blocks in
docs/integration-testing.md.

AC-TEST-001: TC-validate-01 documents a git-checkout precondition, and UJ-12
documents the required ``cd`` step so that the directory is inside a git
checkout before ``kanon validate xml`` is invoked.

AC-TEST-002: RP-wrap-04 documents correct stderr capture via PIPESTATUS and
documents the actual exit code of ``kanon repo selfupdate`` (exit 0, not 1).
"""

import pathlib
import re

import pytest

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent.parent
_INTEGRATION_TESTING_DOC = _REPO_ROOT / "docs" / "integration-testing.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_scenario_block(content: str, scenario_id: str) -> str:
    """Extract the text of a single scenario section by its ID.

    Slices from the heading line for ``scenario_id`` to the next ``###``
    heading (or end of file), returning the block's text for targeted
    assertions.

    Args:
        content: Full text of docs/integration-testing.md.
        scenario_id: Scenario identifier such as ``TC-validate-01``.

    Returns:
        Text of the named scenario section, exclusive of the next heading.

    Raises:
        AssertionError: If the section heading is not found in the document.
    """
    pattern = re.compile(
        rf"###\s+{re.escape(scenario_id)}:.*?(?=###|\Z)",
        re.DOTALL,
    )
    match = pattern.search(content)
    assert match is not None, f"Could not locate scenario section '### {scenario_id}:' in {_INTEGRATION_TESTING_DOC}."
    return match.group(0)


def _read_doc() -> str:
    """Read and return the full text of docs/integration-testing.md.

    Returns:
        File contents as a UTF-8 string.

    Raises:
        AssertionError: If the file does not exist at the expected path.
    """
    assert _INTEGRATION_TESTING_DOC.is_file(), f"docs/integration-testing.md not found at {_INTEGRATION_TESTING_DOC}."
    return _INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-TEST-001: TC-validate-01 git-checkout precondition
# ---------------------------------------------------------------------------


class TestTcValidate01GitPrecondition:
    """AC-TEST-001: TC-validate-01 documents a git-checkout precondition.

    The ``kanon validate xml --repo-root=<path>`` command requires the
    working directory to be inside a git checkout.  The scenario block must
    carry a Precondition comment that makes this dependency explicit so that
    anyone running the integration suite knows to set up the fixture correctly.
    """

    @pytest.mark.unit
    def test_tc_validate_01_section_exists(self) -> None:
        """TC-validate-01 section heading must be present in the document.

        Arrange: Read docs/integration-testing.md.
        Act: Search for the '### TC-validate-01:' heading.
        Assert: The heading is found (basic structural sanity check).
        """
        content = _read_doc()
        _extract_scenario_block(content, "TC-validate-01")

    @pytest.mark.unit
    def test_block_mentions_git_checkout(self) -> None:
        """TC-validate-01 block must contain a git-checkout precondition note.

        Arrange: Read docs/integration-testing.md and extract the
        TC-validate-01 section.
        Act: Search the block for a precondition comment referencing a git
        checkout or git init.
        Assert: The block contains the phrase 'git checkout' or 'git init',
        proving the precondition is documented.

        This assertion fails if the precondition comment is absent (i.e., the
        doc has been reverted to its pre-T3 state).
        """
        content = _read_doc()
        block = _extract_scenario_block(content, "TC-validate-01")
        assert "git checkout" in block or "git init" in block, (
            "TC-validate-01 block is missing a git-checkout precondition note. "
            "Expected a comment such as '<!-- Precondition: ... git checkout "
            "(git init was run ...) -->' to appear in the section, but neither "
            "'git checkout' nor 'git init' was found.\n"
            f"Block content:\n{block}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-001: UJ-12 cd step
# ---------------------------------------------------------------------------


class TestUj12GitPrecondition:
    """AC-TEST-001: UJ-12 documents the required ``cd`` step.

    The manifest validation user journey (UJ-12) calls ``kanon validate xml``
    without ``--repo-root``.  Without a preceding ``cd`` into the manifest
    directory the command cannot discover the git root via ``git rev-parse``.
    The scenario block must include an explicit ``cd "${MANIFEST_PRIMARY_DIR}"``
    (or equivalent git-init step) so testers set up the working directory.
    """

    @pytest.mark.unit
    def test_uj_12_section_exists(self) -> None:
        """UJ-12 section heading must be present in the document.

        Arrange: Read docs/integration-testing.md.
        Act: Search for the '### UJ-12:' heading.
        Assert: The heading is found (basic structural sanity check).
        """
        content = _read_doc()
        _extract_scenario_block(content, "UJ-12")

    @pytest.mark.unit
    def test_block_has_cd_or_git_init_step(self) -> None:
        """UJ-12 block must contain a ``cd`` or ``git init`` step.

        Arrange: Read docs/integration-testing.md and extract the UJ-12
        section.
        Act: Search the block for 'cd ' or 'git init'.
        Assert: At least one of these patterns is present, confirming the
        working-directory setup step is documented.

        This assertion fails if the ``cd "${MANIFEST_PRIMARY_DIR}"`` line is
        absent (i.e., the doc has been reverted to its pre-T3 state).
        """
        content = _read_doc()
        block = _extract_scenario_block(content, "UJ-12")
        assert "cd " in block or "git init" in block, (
            "UJ-12 block is missing a working-directory setup step. "
            "Expected 'cd \"${MANIFEST_PRIMARY_DIR}\"' (or equivalent 'git init') "
            "to appear in the bash block so testers place the shell inside a "
            "git checkout before calling 'kanon validate xml'.\n"
            f"Block content:\n{block}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: RP-wrap-04 stderr capture and exit code
# ---------------------------------------------------------------------------


class TestRpWrap04StderrCapture:
    """AC-TEST-002: RP-wrap-04 documents correct stderr capture and exit code.

    ``kanon repo selfupdate`` is a piped command (``kanon repo selfupdate
    2>&1 | tee ...``).  Using ``$?`` after a pipe captures the exit code of
    ``tee``, not of ``kanon``.  The scenario block must use ``${PIPESTATUS[0]}``
    to capture the kanon exit code correctly, and the documented exit code must
    match the actual behaviour (exit 0, not exit 1).
    """

    @pytest.mark.unit
    def test_rp_wrap_04_section_exists(self) -> None:
        """RP-wrap-04 section heading must be present in the document.

        Arrange: Read docs/integration-testing.md.
        Act: Search for the '### RP-wrap-04:' heading.
        Assert: The heading is found (basic structural sanity check).
        """
        content = _read_doc()
        _extract_scenario_block(content, "RP-wrap-04")

    @pytest.mark.unit
    def test_block_uses_tee_for_output_capture(self) -> None:
        """RP-wrap-04 block must redirect output through tee.

        Arrange: Read docs/integration-testing.md and extract the RP-wrap-04
        section.
        Act: Search the block for 'tee'.
        Assert: 'tee' is present, confirming the combined stdout+stderr
        capture pattern is documented.
        """
        content = _read_doc()
        block = _extract_scenario_block(content, "RP-wrap-04")
        assert "tee" in block, (
            "RP-wrap-04 block does not contain 'tee'. "
            "The scenario must redirect kanon output through 'tee' so that "
            "both the log file and the terminal receive the output.\n"
            f"Block content:\n{block}"
        )

    @pytest.mark.unit
    def test_block_exit_code_uses_pipestatus_or_avoids_pipe(self) -> None:
        """RP-wrap-04 block must use PIPESTATUS to capture the kanon exit code.

        When a command is piped (``cmd | tee``), ``$?`` captures the exit code
        of ``tee``, not of ``cmd``.  The block must use ``${PIPESTATUS[0]}``
        so that the kanon exit code is tested, not tee's.

        Arrange: Read docs/integration-testing.md and extract the RP-wrap-04
        section.
        Act: Search the block for 'PIPESTATUS'.
        Assert: 'PIPESTATUS' is present.

        This assertion fails if the block uses ``exit_code=$?`` without
        PIPESTATUS (i.e., the doc has been reverted to its pre-T3 state).
        """
        content = _read_doc()
        block = _extract_scenario_block(content, "RP-wrap-04")
        assert "PIPESTATUS" in block, (
            "RP-wrap-04 block does not use PIPESTATUS to capture the kanon "
            "exit code. After a pipe ('kanon repo selfupdate 2>&1 | tee ...'), "
            "'$?' captures tee's exit code, not kanon's. "
            "The block must use '${PIPESTATUS[0]}' to get the kanon exit code.\n"
            f"Block content:\n{block}"
        )

    @pytest.mark.unit
    def test_block_exit_code_check_matches_actual_behavior(self) -> None:
        """RP-wrap-04 block must document exit code 0 for selfupdate.

        ``kanon repo selfupdate`` exits 0 when selfupdate is disabled (the
        disabled message is informational, not an error).  The scenario block
        must assert ``exit_code -eq 0``, and the Pass-criteria line must also
        document exit code 0.

        Arrange: Read docs/integration-testing.md and extract the RP-wrap-04
        section.
        Act: Search the block for the pattern 'eq 0'.
        Assert: 'eq 0' is present in the block.

        This assertion fails if the block asserts 'eq 1' (i.e., the doc has
        been reverted to its pre-T3 state).
        """
        content = _read_doc()
        block = _extract_scenario_block(content, "RP-wrap-04")
        assert "eq 0" in block, (
            "RP-wrap-04 block does not assert exit code 0. "
            "'kanon repo selfupdate' exits 0 when selfupdate is disabled; "
            "the scenario must use 'test \"${exit_code}\" -eq 0' and the "
            "Pass-criteria line must document 'Exit code 0'. "
            "Found block does not contain 'eq 0'.\n"
            f"Block content:\n{block}"
        )
