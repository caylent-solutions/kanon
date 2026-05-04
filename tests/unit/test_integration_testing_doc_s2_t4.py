"""Regression-guard for E2-F3-S2-T4: RP-checkout-01 uses a repo-started branch.

`kanon repo checkout` only operates on branches that were previously
created by `kanon repo start`; it does NOT fall through to look up
upstream branches such as `main` in the underlying git checkouts. The
prior RP-checkout-01 scenario invoked `kanon repo checkout main`, which
fails with `MissingBranchError: no project has branch main` because no
project has a repo-tracked branch named `main`.

The fix updates the doc to: (1) explain the limit in prose, (2) check
out the repo-started branch (`mybr`) instead of `main`. This pins the
contract that the scenario exercises the documented checkout flow.
"""

from __future__ import annotations

import pathlib

import pytest


DOC_PATH = pathlib.Path(__file__).resolve().parents[2] / "docs" / "integration-testing.md"


def _load_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _rp_checkout_01_section() -> str:
    doc = _load_doc()
    start = doc.find("### RP-checkout-01: existing branch")
    end = doc.find("### RP-checkout-02:", start)
    assert start >= 0 and end > start, "Could not locate RP-checkout-01 section in doc"
    return doc[start:end]


@pytest.mark.unit
class TestT4RPCheckout01:
    def test_uses_repo_started_branch(self) -> None:
        section = _rp_checkout_01_section()
        # The fix swaps `checkout main` for `checkout mybr` -- the topic
        # branch created in the preceding `repo start` step.
        assert "kanon repo checkout mybr" in section, (
            "RP-checkout-01 must check out the repo-started branch `mybr`, not the upstream `main` branch"
        )

    def test_does_not_attempt_to_checkout_main(self) -> None:
        section = _rp_checkout_01_section()
        # The previous form `kanon repo checkout main` (with or without
        # --all) must be removed; checking it out fails because no project
        # has a repo-tracked branch named `main`.
        assert "kanon repo checkout main" not in section, (
            "RP-checkout-01 must no longer invoke `kanon repo checkout main`; "
            "the kanon repo checkout subcommand only operates on branches "
            "created by `kanon repo start`"
        )

    def test_documents_repo_checkout_limitation(self) -> None:
        section = _rp_checkout_01_section()
        # The fix adds a prose note explaining the limit so future readers
        # understand why the scenario uses a repo-started branch.
        assert "kanon repo checkout" in section
        assert "repo start" in section, (
            "RP-checkout-01 must include a prose note pointing to "
            "`kanon repo start` as the prerequisite for `kanon repo checkout`"
        )

    def test_repo_start_precedes_checkout(self) -> None:
        section = _rp_checkout_01_section()
        start_idx = section.find("kanon repo start mybr --all")
        checkout_idx = section.find("kanon repo checkout mybr")
        assert start_idx >= 0 and checkout_idx >= 0, (
            "Both `kanon repo start mybr --all` and `kanon repo checkout mybr` must appear in the scenario"
        )
        assert start_idx < checkout_idx, (
            "`kanon repo start mybr --all` must run before `kanon repo checkout mybr` "
            "so the topic branch exists when the checkout runs"
        )
