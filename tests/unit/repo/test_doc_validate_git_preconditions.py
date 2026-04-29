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

AC-TEST-002: RP-wrap-04 documents correct stderr capture by redirecting stdout
and stderr to separate log files, and documents the actual exit code of
``kanon repo selfupdate`` (exit 1: selfupdate is disabled in embedded mode).
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

    ``kanon repo selfupdate`` must redirect stdout and stderr to separate log
    files (``2>/tmp/rp-wrap-04-stderr.log 1>/tmp/rp-wrap-04-stdout.log``) so
    that the grep assertion targets stderr exclusively.  The block must also
    assert that stdout is empty and that the exit code is 1 (selfupdate is
    disabled in embedded mode).
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
    def test_block_captures_stderr_separately(self) -> None:
        """RP-wrap-04 block must redirect stderr to a dedicated log file.

        To assert that the disabled message appears on stderr (not stdout),
        the block must redirect stderr (``2>``) and stdout (``1>``) to
        separate log files rather than merging them with ``2>&1``.

        Arrange: Read docs/integration-testing.md and extract the RP-wrap-04
        section.
        Act: Search the block for a ``2>`` stderr redirect.
        Assert: ``2>`` is present, confirming stderr is captured separately.
        """
        content = _read_doc()
        block = _extract_scenario_block(content, "RP-wrap-04")
        assert "2>" in block, (
            "RP-wrap-04 block does not redirect stderr separately (expected '2>'). "
            "The scenario must capture stdout and stderr to separate log files "
            "so that the grep assertion targets stderr exclusively.\n"
            f"Block content:\n{block}"
        )

    @pytest.mark.unit
    def test_block_exit_code_avoids_pipe(self) -> None:
        """RP-wrap-04 block must capture the kanon exit code without a pipe.

        The block uses direct file redirection (``kanon ... 2>... 1>...``)
        rather than a pipe, so ``exit_code=$?`` captures kanon's exit code
        directly.  The block must NOT use a bare ``$?`` after a pipe
        (which would capture the pipe tail's exit code instead).

        Arrange: Read docs/integration-testing.md and extract the RP-wrap-04
        section.
        Act: Search the block for ``exit_code=$?``.
        Assert: ``exit_code=$?`` is present and the block does NOT contain
        ``2>&1 |`` (the old merged-pipe form).
        """
        content = _read_doc()
        block = _extract_scenario_block(content, "RP-wrap-04")
        assert "exit_code=$?" in block, (
            "RP-wrap-04 block does not capture the exit code with 'exit_code=$?'. "
            "The block should use direct redirection so that '$?' reflects "
            "kanon's exit code without an intervening pipe.\n"
            f"Block content:\n{block}"
        )
        assert "2>&1 |" not in block, (
            "RP-wrap-04 block uses '2>&1 |' pipe merge. "
            "The block must redirect stdout and stderr to separate files "
            "so that assertions target stderr exclusively.\n"
            f"Block content:\n{block}"
        )

    @pytest.mark.unit
    def test_block_exit_code_check_matches_actual_behavior(self) -> None:
        """RP-wrap-04 block must document exit code 1 for selfupdate.

        ``kanon repo selfupdate`` exits 1 when selfupdate is disabled (the
        disabled state is an error condition, updated per E2-F2-S2-T2).
        The scenario block must assert ``exit_code -eq 1``, and the
        Pass-criteria line must also document exit code 1.

        Arrange: Read docs/integration-testing.md and extract the RP-wrap-04
        section.
        Act: Search the block for the pattern 'eq 1'.
        Assert: 'eq 1' is present in the block.

        This assertion fails if the block asserts 'eq 0' (i.e., the doc
        reflects the pre-T2 behaviour where selfupdate returned exit 0).
        """
        content = _read_doc()
        block = _extract_scenario_block(content, "RP-wrap-04")
        assert "eq 1" in block, (
            "RP-wrap-04 block does not assert exit code 1. "
            "'kanon repo selfupdate' exits 1 when selfupdate is disabled; "
            "the scenario must use 'test \"${exit_code}\" -eq 1' and the "
            "Pass-criteria line must document 'Exit code 1'. "
            "Found block does not contain 'eq 1'.\n"
            f"Block content:\n{block}"
        )

    @pytest.mark.unit
    def test_block_asserts_stdout_is_empty(self) -> None:
        """RP-wrap-04 block must assert that stdout is empty via ``wc -c``.

        Because stdout is captured to a separate file, the block must verify
        that the file contains zero bytes using ``wc -c``.  This confirms the
        disabled message appears only on stderr.

        Arrange: Read docs/integration-testing.md and extract the RP-wrap-04
        section.
        Act: Search the block for ``wc -c``.
        Assert: ``wc -c`` is present, confirming the stdout-empty assertion
        is documented.
        """
        content = _read_doc()
        block = _extract_scenario_block(content, "RP-wrap-04")
        assert "wc -c" in block, (
            "RP-wrap-04 block does not assert that stdout is empty using 'wc -c'. "
            "The block must verify the stdout log file is empty "
            "(e.g., 'test \"$(wc -c < /tmp/rp-wrap-04-stdout.log)\" -eq 0') "
            "to confirm the disabled message appears only on stderr.\n"
            f"Block content:\n{block}"
        )

    @pytest.mark.unit
    def test_pass_criteria_includes_pipx_suffix(self) -> None:
        """RP-wrap-04 pass criteria must include the full pipx upgrade message.

        The Pass-criteria line must document the full value of the disabled
        message including the ``pipx upgrade kanon-cli`` suffix, so testers
        can grep for the complete string.

        Arrange: Read docs/integration-testing.md and extract the RP-wrap-04
        section.
        Act: Search the block for ``pipx upgrade kanon-cli``.
        Assert: ``pipx upgrade kanon-cli`` is present, confirming the full
        message is documented in the pass criteria.
        """
        content = _read_doc()
        block = _extract_scenario_block(content, "RP-wrap-04")
        assert "pipx upgrade kanon-cli" in block, (
            "RP-wrap-04 pass criteria does not include the full pipx upgrade suffix. "
            "Expected 'pipx upgrade kanon-cli' to appear in the pass criteria line "
            "(e.g., 'stderr contains selfupdate is not available -- upgrade kanon-cli "
            "instead: pipx upgrade kanon-cli').\n"
            f"Block content:\n{block}"
        )
