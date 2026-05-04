"""RP-upload scenarios from `docs/integration-testing.md` §26.

All 15 scenarios require a live Gerrit instance reachable over SSH with push
credentials provisioned in the test environment.  They are skipped in the
development environment per E2-F3-S2-T14.

Scenarios (all skipped):
- RP-upload-01..15
"""

from __future__ import annotations

import pytest

_SKIP_REASON = "E2-F3-S2-T14: requires Gerrit + SSH push credentials not provisioned in dev env"


@pytest.mark.scenario
class TestRPUpload:
    def test_rp_upload_01_dry_run_basic(self) -> None:
        """RP-upload-01: --dry-run basic."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_02_auto_topic(self) -> None:
        """RP-upload-02: -t / --auto-topic."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_03_topic_name(self) -> None:
        """RP-upload-03: --topic=<name>."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_04_hashtag(self) -> None:
        """RP-upload-04: --hashtag=a,b."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_05_add_hashtag(self) -> None:
        """RP-upload-05: --add-hashtag."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_06_label(self) -> None:
        """RP-upload-06: --label / -l."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_07_description(self) -> None:
        """RP-upload-07: --description / -m."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_08_reviewer(self) -> None:
        """RP-upload-08: --re=<reviewer>."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_09_cc(self) -> None:
        """RP-upload-09: --cc=<email>."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_10_private(self) -> None:
        """RP-upload-10: --private."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_11_wip(self) -> None:
        """RP-upload-11: --wip."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_12_current_branch(self) -> None:
        """RP-upload-12: --current-branch / -c."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_13_branch_exclude(self) -> None:
        """RP-upload-13: --branch-exclude=<branch> / -x."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_14_auto_approve(self) -> None:
        """RP-upload-14: --auto-approve / -a."""
        pytest.skip(_SKIP_REASON)

    def test_rp_upload_15_receive_pack(self) -> None:
        """RP-upload-15: --receive-pack."""
        pytest.skip(_SKIP_REASON)
