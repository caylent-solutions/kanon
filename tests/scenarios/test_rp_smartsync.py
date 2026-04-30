"""RP-smartsync-01: `kanon repo smartsync` smoke test.

Automates §26 of `docs/integration-testing.md`.
"""

from __future__ import annotations

import pytest


@pytest.mark.scenario
class TestRPSmartSync:
    """RP-smartsync-01: smartsync subcommand smoke test."""

    def test_rp_smartsync_01_smoke(self) -> None:
        """RP-smartsync-01: `kanon repo smartsync` requires manifest-server XMLRPC infra.

        Skipped because the command requires a live manifest-server endpoint
        (XMLRPC) to resolve the smart manifest, which cannot be simulated in
        an automated local test environment.
        """
        pytest.skip(reason="requires manifest-server XMLRPC infra")
