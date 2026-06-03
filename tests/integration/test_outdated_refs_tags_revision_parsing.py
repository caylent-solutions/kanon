"""Integration tests for 'kanon outdated' with refs/tags/X.Y.Z and refs/heads/<branch> revisions.

Reproduces DEFECT-007: `kanon outdated` fails with "invalid version constraint"
when the .kanon file stores a REVISION in the form `refs/tags/1.0.0` (which is
exactly what `kanon add foo@==1.0.0` writes). The branch-shaped variant
`refs/heads/main` surfaces a related failure when the branch lookup incorrectly
appends the prefix a second time.

These tests are RED against unfixed code (with DEFECT-001 / E22 fix in place).
T2 carries the GREEN-phase fix in `src/kanon_cli/commands/outdated.py`.

The tests use `_create_manifest_repo_with_tags` (spec §3.1) from
`tests.integration.test_add_core` and inherit the autouse fixtures from
`tests/integration/conftest.py` (`_mock_resolve_ref_to_sha`,
`_mock_check_sha_reachable`, `_auto_create_manifest_on_walk`,
`_default_allow_insecure_remotes`) so no real GitHub remote is contacted.

Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
Section 4 E30 (Failing test + Verification + Edge cases), §3.1, §3.2, §13 D5.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from tests.integration.test_add_core import (
    _create_manifest_repo_with_tags,
    _run_kanon,
)


# ---------------------------------------------------------------------------
# .kanon file template for the refs/heads case (written directly).
# The refs/tags case is set up by running 'kanon add foo@==1.0.0' so that
# the REVISION is written by the real add command, not constructed by hand.
# ---------------------------------------------------------------------------

_KANON_REFS_HEADS_TEMPLATE = textwrap.dedent("""\
    GITBASE=file:///unused
    CLAUDE_MARKETPLACES_DIR=/tmp/.claude-marketplaces
    KANON_MARKETPLACE_INSTALL=false
    KANON_SOURCE_{name_upper}_URL={url}
    KANON_SOURCE_{name_upper}_REVISION={revision}
    KANON_SOURCE_{name_upper}_PATH=./{name_lower}
""")


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOutdatedRefsTagsParsing:
    """kanon outdated must accept refs/tags/X.Y.Z and refs/heads/<branch> REVISION forms.

    DEFECT-007: the outdated command passes 'refs/tags/1.0.0' verbatim to the
    PEP 440 SpecifierSet, which rejects '1.0.0' (a bare version, not a
    constraint) with "invalid version constraint '1.0.0'".

    The branch-shaped variant 'refs/heads/main' is classified as BRANCH but
    the outdated command passes the full 'refs/heads/main' string as the branch
    argument to _list_branch_head, which prepends 'refs/heads/' again, so the
    lookup for 'refs/heads/refs/heads/main' fails.

    Both issues are fixed by E30-F1-S1-T2.

    Spec §4 E30 Failing test, §3.1, §3.2, §13 D5.
    """

    @pytest.mark.parametrize(
        "revision,expected_display",
        [
            # Case 1: refs/tags/1.0.0 -- written by 'kanon add foo@==1.0.0'.
            # The spec D5 decision normalises the display to the bare version.
            # Accept either the bare version '1.0.0' or the full 'refs/tags/1.0.0'.
            ("refs/tags/1.0.0", ("1.0.0", "refs/tags/1.0.0")),
            # Case 2: refs/heads/main -- a branch-shaped ref stored verbatim.
            # The spec D5 decision normalises the display to the bare branch name.
            # Accept either 'main' or 'refs/heads/main'.
            ("refs/heads/main", ("main", "refs/heads/main")),
        ],
    )
    def test_outdated_accepts_refs_tags_form_revision(
        self,
        tmp_path: pathlib.Path,
        revision: str,
        expected_display: tuple[str, str],
    ) -> None:
        """kanon outdated exits 0 and shows the foo row for refs/tags and refs/heads revisions.

        Setup:
        - For refs/tags/1.0.0: run 'kanon add foo@==1.0.0 --catalog-source <url>'
          so the REVISION is written by the real add command.
        - For refs/heads/main: write .kanon directly with the refs/heads/main REVISION.

        Assert:
        - exit code is 0.
        - stdout table contains a row whose name column is 'FOO'.
        - stdout table contains the expected display token in the 'current' column.
        - For the branch case: stdout contains 'branch' or 'none' in the
          upgrade-type column (spec D5).
        """
        bare = _create_manifest_repo_with_tags(
            tmp_path / "catalog",
            entry_names=["foo"],
            tags=["1.0.0"],
        )
        catalog_source = f"file://{bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        if revision.startswith("refs/tags/"):
            # Use the real 'kanon add' command so the REVISION comes from the
            # add command's resolver (which writes 'refs/tags/1.0.0').
            add_result = _run_kanon(
                [
                    "add",
                    "foo@==1.0.0",
                    "--catalog-source",
                    catalog_source,
                ],
                cwd=workspace,
            )
            assert add_result.returncode == 0, (
                f"kanon add setup failed (expected 0, got {add_result.returncode}).\n"
                f"stdout: {add_result.stdout!r}\nstderr: {add_result.stderr!r}"
            )
        else:
            # Write .kanon directly with the refs/heads/main REVISION.
            # The catalog bare URL is used so the catalog lookup can proceed.
            kanon_file = workspace / ".kanon"
            kanon_file.write_text(
                _KANON_REFS_HEADS_TEMPLATE.format(
                    name_upper="FOO",
                    name_lower="foo",
                    url=f"file://{bare}",
                    revision=revision,
                )
            )
            kanon_file.chmod(0o644)

        # Run 'kanon outdated' with the same catalog source.
        env = dict(os.environ)
        env.pop("KANON_CATALOG_SOURCE", None)
        outdated_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kanon_cli",
                "outdated",
                "--catalog-source",
                catalog_source,
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(workspace),
        )

        assert outdated_result.returncode == 0, (
            f"Expected exit 0 for revision {revision!r}, "
            f"got {outdated_result.returncode}.\n"
            f"stdout: {outdated_result.stdout!r}\n"
            f"stderr: {outdated_result.stderr!r}"
        )

        # Accept either uppercase 'FOO' (refs/heads case: template writes
        # KANON_SOURCE_FOO_URL) or lowercase 'foo' (refs/tags case: kanon add
        # lowercases via derive_source_name).
        stdout_lower = outdated_result.stdout.lower()
        assert "foo" in stdout_lower, (
            f"Expected source name 'foo' (case-insensitive) in output for revision {revision!r}.\n"
            f"stdout: {outdated_result.stdout!r}"
        )

        # The 'current' column must display one of the accepted display tokens
        # per spec D5 (normalized form preferred, full form also accepted).
        display_a, display_b = expected_display
        assert display_a in outdated_result.stdout or display_b in outdated_result.stdout, (
            f"Expected either {display_a!r} or {display_b!r} in the 'current' column "
            f"for revision {revision!r}.\n"
            f"stdout: {outdated_result.stdout!r}"
        )

        if revision.startswith("refs/heads/"):
            # For branch-shaped revisions the upgrade-type column must read
            # 'branch' or 'none' per spec D5.
            assert "branch" in outdated_result.stdout or "none" in outdated_result.stdout, (
                f"Expected 'branch' or 'none' in upgrade-type column for "
                f"branch revision {revision!r}.\n"
                f"stdout: {outdated_result.stdout!r}"
            )
