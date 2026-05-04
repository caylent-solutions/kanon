"""Regression-guard for E2-F3-S2-T6: KS section cs-catalog HEAD reset.

The KS scenarios in §17 of `docs/integration-testing.md` use
`kanon repo manifest --revision-as-tag` on the cs-catalog/catalog
project. After the §14 CS scenarios run, the catalog repo's `main`
HEAD has commits beyond the last semver tag (3.0.0), so
`--revision-as-tag` warns "no exact tag at HEAD; revision unchanged"
and the KS pass-check (`grep -q refs/tags/<expected>`) always fails.

The fix adds a `git reset --hard refs/tags/3.0.0` step at the top of
the §17 fixture block so the catalog repo's main is pinned to the
highest semver tag before KS scenarios run.
"""

from __future__ import annotations

import pathlib

import pytest


DOC_PATH = pathlib.Path(__file__).resolve().parents[2] / "docs" / "integration-testing.md"


def _load_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.mark.unit
class TestT6KSFixtureReset:
    def test_section_17_includes_reset_step(self) -> None:
        doc = _load_doc()
        # Slice §17 from its heading to the start of §18.
        start = doc.find("## 17. Category 16: PEP 440 Constraints in `.kanon`")
        end = doc.find("## 18. Category 17:")
        assert start >= 0 and end > start, "Could not locate §17 in doc"
        section = doc[start:end]

        assert 'git -C "${CS_CATALOG_DIR}" reset --hard refs/tags/3.0.0' in section, (
            "§17 must include `git reset --hard refs/tags/3.0.0` to pin "
            "cs-catalog HEAD to a known semver tag before KS scenarios run"
        )

    def test_reset_appears_before_ks_run_definition(self) -> None:
        doc = _load_doc()
        reset_idx = doc.find("reset --hard refs/tags/3.0.0")
        ks_run_idx = doc.find("ks_run() {")
        assert reset_idx >= 0 and ks_run_idx >= 0
        assert reset_idx < ks_run_idx, "The reset step must appear before the ks_run() helper definition"

    def test_reset_documented_in_prose(self) -> None:
        doc = _load_doc()
        # The fix also adds an explanatory note describing why the reset is
        # required.
        assert "CS-catalog HEAD reset" in doc, (
            "§17 must include a prose note explaining why the cs-catalog reset is required"
        )
