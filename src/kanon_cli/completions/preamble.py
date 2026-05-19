"""Shell completion preamble stubs for shtab integration.

This module exports PREAMBLE, a dict mapping shell names to preamble
script fragments that shtab prepends to the generated completion script.

The bash and zsh entries are populated by E7-F1-S1-T2. For this task
(T1) both are empty strings so the import chain is sound and the
completion subcommand can be exercised end-to-end without the helper
functions that T2 will add.
"""

from __future__ import annotations

PREAMBLE: dict[str, str] = {
    "bash": "",
    "zsh": "",
}
