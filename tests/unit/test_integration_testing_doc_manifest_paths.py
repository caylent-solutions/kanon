"""Regression-guard tests for docs/integration-testing.md manifest paths.

These tests assert that the 13 affected scenario blocks (TC-install-01/02/03/04,
TC-clean-01/02, UJ-03, UJ-04, UJ-06, UJ-08, UJ-09, ``rp_ro_setup``, and
RP-wrap-01/02/03) reference manifest files at their actual fixture
locations under ``repo-specs/`` rather than at the repository root. The
fixtures (defined elsewhere in the same doc) write manifests to
``${MANIFEST_PRIMARY_DIR}/repo-specs/*.xml`` and
``${MANIFEST_COLLISION_DIR}/repo-specs/collision.xml``; tests that point
at root-level ``alpha-only.xml``, ``bravo-only.xml``, ``collision.xml``,
or ``default.xml`` will fail strict-doc-verbatim re-runs because the
file is not where the test claims it is.

Each test extracts the relevant scenario block from
``docs/integration-testing.md`` and asserts the corrected path is
present and the obsolete root-level form is absent. Implements
AC-DOC-001, AC-DOC-002, AC-FUNC-001, and AC-TEST-001 of E2-F3-S1-T6.
"""

from __future__ import annotations

import pathlib
import re

import pytest


DOC_PATH = pathlib.Path(__file__).resolve().parents[2] / "docs" / "integration-testing.md"


def _load_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _scenario_block(doc: str, heading: str) -> str:
    """Return the body of a ``### <heading>`` block up to the next ``### ``."""
    pattern = re.compile(
        r"^### " + re.escape(heading) + r"(?:\b|:|$).*?(?=^### |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(doc)
    assert match is not None, f"Scenario block '{heading}' not found in {DOC_PATH}"
    return match.group(0)


def _rp_ro_setup_block(doc: str) -> str:
    """Return the body of the ``rp_ro_setup`` bash function definition.

    Matches from ``rp_ro_setup() {`` up to the first closing ``}`` that
    appears at column 0 (the function-terminator brace; ``${KANON_TEST_ROOT}``
    interpolation braces sit inside quoted strings indented further in).
    """
    pattern = re.compile(
        r"^rp_ro_setup\(\)\s*\{.*?^\}",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(doc)
    assert match is not None, f"rp_ro_setup() function not found in {DOC_PATH}"
    return match.group(0)


# ---------------------------------------------------------------------------
# TC-install-01..04: KANON_SOURCE_a_PATH MUST be repo-specs/-prefixed.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTCInstallScenarios:
    @pytest.mark.parametrize(
        "scenario_id",
        ["TC-install-01", "TC-install-02", "TC-install-03", "TC-install-04"],
    )
    def test_alpha_path_is_repo_specs_prefixed(self, scenario_id: str) -> None:
        block = _scenario_block(_load_doc(), scenario_id)
        assert "KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml" in block, (
            f"{scenario_id}: missing repo-specs/-prefixed alpha-only.xml path"
        )

    @pytest.mark.parametrize(
        "scenario_id",
        ["TC-install-01", "TC-install-02", "TC-install-03", "TC-install-04"],
    )
    def test_no_root_level_alpha_only(self, scenario_id: str) -> None:
        block = _scenario_block(_load_doc(), scenario_id)
        assert "KANON_SOURCE_a_PATH=alpha-only.xml" not in block, (
            f"{scenario_id}: still references root-level alpha-only.xml"
        )


# ---------------------------------------------------------------------------
# TC-clean-01..02: same fix as TC-install.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTCCleanScenarios:
    @pytest.mark.parametrize("scenario_id", ["TC-clean-01", "TC-clean-02"])
    def test_alpha_path_is_repo_specs_prefixed(self, scenario_id: str) -> None:
        block = _scenario_block(_load_doc(), scenario_id)
        assert "KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml" in block, (
            f"{scenario_id}: missing repo-specs/-prefixed alpha-only.xml path"
        )

    @pytest.mark.parametrize("scenario_id", ["TC-clean-01", "TC-clean-02"])
    def test_no_root_level_alpha_only(self, scenario_id: str) -> None:
        block = _scenario_block(_load_doc(), scenario_id)
        assert "KANON_SOURCE_a_PATH=alpha-only.xml" not in block, (
            f"{scenario_id}: still references root-level alpha-only.xml"
        )


# ---------------------------------------------------------------------------
# UJ-03: alpha and bravo paths both repo-specs/-prefixed.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUJ03MultiSource:
    def test_alpha_path_is_repo_specs_prefixed(self) -> None:
        block = _scenario_block(_load_doc(), "UJ-03")
        assert "KANON_SOURCE_alpha_PATH=repo-specs/alpha-only.xml" in block

    def test_bravo_path_is_repo_specs_prefixed(self) -> None:
        block = _scenario_block(_load_doc(), "UJ-03")
        assert "KANON_SOURCE_bravo_PATH=repo-specs/bravo-only.xml" in block

    def test_no_root_level_alpha_only(self) -> None:
        block = _scenario_block(_load_doc(), "UJ-03")
        assert "KANON_SOURCE_alpha_PATH=alpha-only.xml" not in block

    def test_no_root_level_bravo_only(self) -> None:
        block = _scenario_block(_load_doc(), "UJ-03")
        assert "KANON_SOURCE_bravo_PATH=bravo-only.xml" not in block


# ---------------------------------------------------------------------------
# UJ-04 / UJ-08 / UJ-09: alpha path repo-specs/-prefixed.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUJSingleSourceScenarios:
    @pytest.mark.parametrize("scenario_id", ["UJ-04", "UJ-08", "UJ-09"])
    def test_alpha_path_is_repo_specs_prefixed(self, scenario_id: str) -> None:
        block = _scenario_block(_load_doc(), scenario_id)
        assert "KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml" in block, (
            f"{scenario_id}: missing repo-specs/-prefixed alpha-only.xml path"
        )

    @pytest.mark.parametrize("scenario_id", ["UJ-04", "UJ-08", "UJ-09"])
    def test_no_root_level_alpha_only(self, scenario_id: str) -> None:
        block = _scenario_block(_load_doc(), scenario_id)
        assert "KANON_SOURCE_a_PATH=alpha-only.xml" not in block, (
            f"{scenario_id}: still references root-level alpha-only.xml"
        )


# ---------------------------------------------------------------------------
# UJ-06: collision detection requires both source-a (primary) and source-b
# (collision) paths to be repo-specs/-prefixed AND source-b to use
# MANIFEST_COLLISION_DIR rather than MANIFEST_PRIMARY_DIR.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUJ06CollisionDetection:
    def test_alpha_path_is_repo_specs_prefixed(self) -> None:
        block = _scenario_block(_load_doc(), "UJ-06")
        assert "KANON_SOURCE_a_PATH=repo-specs/alpha-only.xml" in block

    def test_b_url_uses_collision_dir(self) -> None:
        block = _scenario_block(_load_doc(), "UJ-06")
        assert "KANON_SOURCE_b_URL=file://${MANIFEST_COLLISION_DIR}" in block, (
            "UJ-06 source-b URL must point at MANIFEST_COLLISION_DIR (not MANIFEST_PRIMARY_DIR)"
        )

    def test_b_path_is_repo_specs_collision(self) -> None:
        block = _scenario_block(_load_doc(), "UJ-06")
        assert "KANON_SOURCE_b_PATH=repo-specs/collision.xml" in block

    def test_no_b_path_root_level_collision(self) -> None:
        block = _scenario_block(_load_doc(), "UJ-06")
        assert "KANON_SOURCE_b_PATH=collision.xml" not in block, "UJ-06 must not reference root-level collision.xml"

    def test_no_b_url_primary_dir(self) -> None:
        block = _scenario_block(_load_doc(), "UJ-06")
        assert "KANON_SOURCE_b_URL=file://${MANIFEST_PRIMARY_DIR}" not in block, (
            "UJ-06 source-b must not point at MANIFEST_PRIMARY_DIR"
        )


# ---------------------------------------------------------------------------
# rp_ro_setup() helper used by rp-status / rp-info / rp-manifest scenarios:
# the kanon repo init invocation must use -m repo-specs/packages.xml.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRpRoSetup:
    def test_uses_repo_specs_packages_xml(self) -> None:
        block = _rp_ro_setup_block(_load_doc())
        assert "-m repo-specs/packages.xml" in block, "rp_ro_setup must reference -m repo-specs/packages.xml"

    def test_does_not_use_root_default_xml(self) -> None:
        block = _rp_ro_setup_block(_load_doc())
        assert "-m default.xml" not in block, (
            "rp_ro_setup must not reference -m default.xml (fixture has no default.xml)"
        )


# ---------------------------------------------------------------------------
# RP-wrap-01/02/03: each kanon repo init invocation must use
# -m repo-specs/packages.xml.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRPWrapScenarios:
    @pytest.mark.parametrize("scenario_id", ["RP-wrap-01", "RP-wrap-02", "RP-wrap-03"])
    def test_uses_repo_specs_packages_xml(self, scenario_id: str) -> None:
        block = _scenario_block(_load_doc(), scenario_id)
        assert "-m repo-specs/packages.xml" in block, f"{scenario_id} must use -m repo-specs/packages.xml"

    @pytest.mark.parametrize("scenario_id", ["RP-wrap-01", "RP-wrap-02", "RP-wrap-03"])
    def test_does_not_use_root_default_xml(self, scenario_id: str) -> None:
        block = _scenario_block(_load_doc(), scenario_id)
        assert "-m default.xml" not in block, f"{scenario_id} must not reference -m default.xml"


# ---------------------------------------------------------------------------
# Global guards: across the full doc, no scenario should declare a
# root-level alpha/bravo/collision manifest path inside a .kanon block.
# These provide a wider safety net beyond the per-scenario asserts above.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGlobalNoResidualRootLevelPaths:
    def test_no_root_level_kanon_source_a_path(self) -> None:
        doc = _load_doc()
        # The .kanon variable form is the contract this Task fixed; per-fixture
        # bash sources may reference the root file when constructing fixtures,
        # but a .kanon assignment of the bare form is always wrong.
        assert "\nKANON_SOURCE_a_PATH=alpha-only.xml\n" not in doc, (
            "Some .kanon block still assigns root-level alpha-only.xml"
        )

    def test_no_root_level_kanon_source_alpha_path(self) -> None:
        doc = _load_doc()
        assert "\nKANON_SOURCE_alpha_PATH=alpha-only.xml\n" not in doc

    def test_no_root_level_kanon_source_bravo_path(self) -> None:
        doc = _load_doc()
        assert "\nKANON_SOURCE_bravo_PATH=bravo-only.xml\n" not in doc

    def test_no_root_level_kanon_source_b_collision(self) -> None:
        doc = _load_doc()
        assert "\nKANON_SOURCE_b_PATH=collision.xml\n" not in doc


# ---------------------------------------------------------------------------
# Coverage cross-checks: every named scenario the fix targets is present in
# the doc, and the fixture writes manifests to repo-specs/ (the location
# the corrected paths point at).
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCoverageSanity:
    @pytest.mark.parametrize(
        "scenario_id",
        [
            "TC-install-01",
            "TC-install-02",
            "TC-install-03",
            "TC-install-04",
            "TC-clean-01",
            "TC-clean-02",
            "UJ-03",
            "UJ-04",
            "UJ-06",
            "UJ-08",
            "UJ-09",
            "RP-wrap-01",
            "RP-wrap-02",
            "RP-wrap-03",
        ],
    )
    def test_scenario_block_exists(self, scenario_id: str) -> None:
        """Every scenario this Task targets has a heading in the doc."""
        doc = _load_doc()
        assert f"### {scenario_id}" in doc, f"Expected '### {scenario_id}' heading not found in integration-testing.md"

    def test_fixture_writes_packages_xml_under_repo_specs(self) -> None:
        """The fixture setup that the corrected paths point at must create
        manifests under repo-specs/, not at the manifest-repo root."""
        doc = _load_doc()
        assert "cat > repo-specs/packages.xml" in doc, (
            "MANIFEST_PRIMARY_DIR fixture must create packages.xml under repo-specs/"
        )

    def test_fixture_writes_collision_xml_under_repo_specs(self) -> None:
        doc = _load_doc()
        assert "cat > repo-specs/collision.xml" in doc, (
            "MANIFEST_COLLISION_DIR fixture must create collision.xml under repo-specs/"
        )
