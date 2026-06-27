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


_KANON_REFS_HEADS_TEMPLATE = textwrap.dedent("""\
    KANON_SOURCE_{name_upper}_URL={url}
    KANON_SOURCE_{name_upper}_REF={revision}
    KANON_SOURCE_{name_upper}_PATH=./{name_lower}
    KANON_SOURCE_{name_upper}_NAME={name_upper}
    KANON_SOURCE_{name_upper}_GITBASE=https://example.com
""")


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
            ("refs/tags/1.0.0", ("1.0.0", "refs/tags/1.0.0")),
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

        env = dict(os.environ)
        env.pop("KANON_CATALOG_SOURCES", None)
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

        stdout_lower = outdated_result.stdout.lower()
        assert "foo" in stdout_lower, (
            f"Expected source name 'foo' (case-insensitive) in output for revision {revision!r}.\n"
            f"stdout: {outdated_result.stdout!r}"
        )

        display_a, display_b = expected_display
        assert display_a in outdated_result.stdout or display_b in outdated_result.stdout, (
            f"Expected either {display_a!r} or {display_b!r} in the 'current' column "
            f"for revision {revision!r}.\n"
            f"stdout: {outdated_result.stdout!r}"
        )

        if revision.startswith("refs/heads/"):
            assert "branch" in outdated_result.stdout or "none" in outdated_result.stdout, (
                f"Expected 'branch' or 'none' in upgrade-type column for "
                f"branch revision {revision!r}.\n"
                f"stdout: {outdated_result.stdout!r}"
            )

    def test_outdated_accepts_namespaced_exact_tag_revision(self, tmp_path: pathlib.Path) -> None:
        """kanon outdated handles a namespaced exact-tag REVISION (refs/tags/<name>/<ver>).

        Regression for caylent-solutions/kanon#85: ``kanon add foo`` against a
        catalog whose tags are namespaced (``foo/1.0.0``) writes
        ``KANON_SOURCE_FOO_REF=refs/tags/foo/1.0.0``; outdated previously raised
        ``invalid version constraint '1.0.0'`` because the namespaced exact tag
        was not normalised to ``==``. Now it resolves and reports the available
        upgrade to ``1.1.0``.
        """
        bare = _create_manifest_repo_with_tags(
            tmp_path / "catalog",
            entry_names=["foo"],
            tags=["foo/1.0.0", "foo/1.1.0"],
        )
        catalog_source = f"file://{bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        add_result = _run_kanon(
            ["add", "foo@==1.0.0", "--catalog-source", catalog_source],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add setup failed (expected 0, got {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\nstderr: {add_result.stderr!r}"
        )
        kanon_text = (workspace / ".kanon").read_text(encoding="utf-8")
        assert "refs/tags/foo/1.0.0" in kanon_text, f"expected the namespaced exact tag in .kanon; got:\n{kanon_text}"

        env = dict(os.environ)
        env.pop("KANON_CATALOG_SOURCES", None)
        outdated_result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "outdated", "--catalog-source", catalog_source],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(workspace),
        )

        assert outdated_result.returncode == 0, (
            f"Expected exit 0 for namespaced exact tag, got {outdated_result.returncode}.\n"
            f"stdout: {outdated_result.stdout!r}\nstderr: {outdated_result.stderr!r}"
        )
        assert "invalid version constraint" not in outdated_result.stderr, (
            f"outdated still raises the constraint error.\nstderr: {outdated_result.stderr!r}"
        )
        assert "1.0.0" in outdated_result.stdout and "1.1.0" in outdated_result.stdout, (
            f"Expected current 1.0.0 and latest 1.1.0 in the outdated table.\nstdout: {outdated_result.stdout!r}"
        )
