"""Unit tests verifying RP-manifest-04..08 scenario blocks in
docs/integration-testing.md reference only flags present in
subcmds/manifest.py::Manifest._Options().

AC-TEST-001: Five RP-manifest-NN scenario blocks reference only real flags.
AC-TEST-002: Stale flag names are absent from the rewritten scenario blocks.
"""

import pathlib
import re

import pytest


_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent.parent
_INTEGRATION_TESTING_DOC = _REPO_ROOT / "docs" / "integration-testing.md"


_STALE_FLAGS = [
    "--revision-as-tag",
    "--suppress-upstream",
    "--formatted",
    "--ignore-local-manifests",
]


_SCENARIO_CORRECT_FLAGS = [
    ("RP-manifest-04", "--revision-as-HEAD"),
    ("RP-manifest-05", "--suppress-upstream-revision"),
    ("RP-manifest-06", "--suppress-dest-branch"),
    ("RP-manifest-07", "--pretty"),
    ("RP-manifest-08", "--no-local-manifests"),
]


def _stale_flag_present(block: str, stale_flag: str) -> bool:
    """Return True if ``stale_flag`` appears as a complete flag token in ``block``.

    Uses a word-boundary pattern so that ``--suppress-upstream`` does NOT match
    inside ``--suppress-upstream-revision``.  A stale flag token is recognised
    when it is followed by whitespace, a pipe character, a newline, or end of
    string -- i.e. not by any further hyphen-prefixed characters.

    Args:
        block: Combined text of the five RP-manifest-04..08 sections.
        stale_flag: The obsolete CLI flag string to detect.

    Returns:
        True if the stale flag appears as a standalone token; False otherwise.
    """
    pattern = re.compile(re.escape(stale_flag) + r"(?![-\w])")
    return bool(pattern.search(block))


def _extract_scenario_block(content: str, scenario_id: str) -> str:
    """Extract the text of a single RP-manifest-NN section.

    Slices from the heading line for ``scenario_id`` to the next ``###`` heading
    (or end of file), returning the block's text for targeted assertions.

    Args:
        content: Full text of docs/integration-testing.md.
        scenario_id: Scenario identifier such as ``RP-manifest-04``.

    Returns:
        Text of the named scenario section, exclusive of the next heading.
    """
    pattern = re.compile(
        rf"###\s+{re.escape(scenario_id)}:.*?(?=###|\Z)",
        re.DOTALL,
    )
    match = pattern.search(content)
    assert match is not None, f"Could not locate scenario section '### {scenario_id}:' in {_INTEGRATION_TESTING_DOC}."
    return match.group(0)


@pytest.mark.unit
@pytest.mark.parametrize(
    "scenario_id,expected_flag",
    _SCENARIO_CORRECT_FLAGS,
    ids=[s for s, _ in _SCENARIO_CORRECT_FLAGS],
)
class TestRpManifestCorrectFlagsPresent:
    """AC-TEST-001: Each RP-manifest-04..08 block contains the real flag name.

    Reads docs/integration-testing.md and locates each scenario section. The
    bash code block within each section must contain the flag registered in
    manifest.py::Manifest._Options() rather than any stale alias.
    """

    def test_scenario_block_contains_real_flag(
        self,
        scenario_id: str,
        expected_flag: str,
    ) -> None:
        """Scenario block for ``scenario_id`` must contain ``expected_flag``.

        Args:
            scenario_id: e.g. ``RP-manifest-04``.
            expected_flag: Real CLI flag from manifest.py::_Options().
        """
        assert _INTEGRATION_TESTING_DOC.is_file(), (
            f"docs/integration-testing.md not found at {_INTEGRATION_TESTING_DOC}."
        )
        content = _INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        block = _extract_scenario_block(content, scenario_id)
        assert expected_flag in block, (
            f"Scenario {scenario_id}: expected real flag {expected_flag!r} to be present "
            f"in the scenario block, but it was not found.\n"
            f"Block content:\n{block}"
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "stale_flag",
    _STALE_FLAGS,
    ids=_STALE_FLAGS,
)
class TestRpManifestStaleFlags:
    """AC-TEST-002: Stale flag names do not appear anywhere in RP-manifest-04..08.

    Each stale flag is checked against the combined text of all five scenario
    blocks. A match in any block is a failure.
    """

    def test_stale_flag_absent_from_all_rp_manifest_blocks(
        self,
        stale_flag: str,
    ) -> None:
        """``stale_flag`` must not appear in any of the five scenario blocks.

        Args:
            stale_flag: Incorrect flag name that was replaced in the doc.
        """
        assert _INTEGRATION_TESTING_DOC.is_file(), (
            f"docs/integration-testing.md not found at {_INTEGRATION_TESTING_DOC}."
        )
        content = _INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        scenario_ids = [s for s, _ in _SCENARIO_CORRECT_FLAGS]
        combined_blocks = "\n".join(_extract_scenario_block(content, sid) for sid in scenario_ids)
        assert not _stale_flag_present(combined_blocks, stale_flag), (
            f"Stale flag {stale_flag!r} was found as a standalone token in one or more "
            f"of the RP-manifest-04..08 scenario blocks. It must be replaced with the "
            f"real flag registered in manifest.py::Manifest._Options().\n"
            f"Combined block excerpt (lines containing the stale fragment):\n"
            + "\n".join(line for line in combined_blocks.splitlines() if stale_flag in line)
        )
