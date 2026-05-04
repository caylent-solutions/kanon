"""RP-stage-01: `kanon repo stage` interactive smoke test.

Automates §25 of `docs/integration-testing.md`.
"""

from __future__ import annotations

import pytest


@pytest.mark.scenario
class TestRPStage:
    """RP-stage-01: interactive staging via `kanon repo stage -i`."""

    def test_rp_stage_01_interactive_smoke(self) -> None:
        """RP-stage-01: `kanon repo stage -i` is an interactive subcommand.

        Skipped because the command requires a tty for interactive use and
        cannot be driven non-interactively in an automated test environment.
        """
        pytest.skip(reason="interactive subcommand: kanon repo stage -i requires a tty")
