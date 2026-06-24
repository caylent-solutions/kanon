"""Integration-test conftest for the embedded repo-tool suite.

The embedded Google "repo" tool (src/kanon_cli/repo/**) is a POSIX-oriented
subsystem: it shells out to git, relies on fork-based process isolation, POSIX
signal handling, and symlink semantics. kanon shells out to it and runs its
suite in full on the single Linux CI set. Every test under tests/integration/repo/
already carries @pytest.mark.integration on its own, so no marker plumbing is
applied here.
"""

from __future__ import annotations
