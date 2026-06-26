"""Integration tests for DEFECT-003: placeholder handling in `kanon add` and `kanon install`.

Failing (RED) tests that assert:

1. `kanon add` does NOT write literal `<YOUR_GIT_ORG_BASE_URL>` or `<true|false>`
   placeholders into the generated `.kanon` file; instead it derives GITBASE from
   the catalog-source URL (scheme + authority).

2. `kanon install` FAILS FAST with an "unresolved placeholder" diagnostic (naming
   the offending `.kanon` line number) when the `.kanon` file contains a literal
   `<...>` placeholder value.

Both defects are described in DEFECT-003 (spec/defect-resolution-and-fixture-automation-2026-06/spec.md).

Both tests use the synthetic-fixture helper `_create_manifest_repo_with_tags` from
`tests.integration.test_add_core` and inherit all autouse fixtures defined in
`tests/integration/conftest.py` (URL-scheme policy bypass, ref-resolution mocks,
manifest auto-create). No manual setup of those fixtures is required in the test
bodies.

Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
Section 4 E28 (Failing test + Verification + Edge cases), Section 3.1 (synthetic-
fixture helpers), Section 3.2 (autouse fixtures).
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


@pytest.mark.integration
class TestKanonAddNoPlaceholders:
    """kanon add must derive GITBASE from the catalog URL, not write literal placeholders."""

    def test_add_does_not_write_yourgitorgbaseurl_placeholder(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """kanon add never writes literal `<YOUR_GIT_ORG_BASE_URL>` / `<true|false>`.

        Asserts the DEFECT-003 conditions plus the generalized env-var behavior:

        1. The generated `.kanon` does NOT contain the literal string
           ``<YOUR_GIT_ORG_BASE_URL>``.
        2. The generated `.kanon` does NOT contain the literal string
           ``<true|false>``.
        3. This entry's manifest references no ``${GITBASE}`` placeholder, so add
           writes NO ``KANON_SOURCE_foo_GITBASE=`` line at all (the env-var line is
           emitted only when the manifest needs the var). The four structural keys
           are still written.

        The derived-GITBASE value for a manifest that DOES reference ``${GITBASE}``
        is covered by the dedicated detection test in test_add_env_var_detection.py.
        """
        bare = _create_manifest_repo_with_tags(
            tmp_path / "catalog",
            entry_names=["foo"],
            tags=["1.0.0"],
        )
        catalog_source = f"file://{bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _run_kanon(
            [
                "add",
                "foo",
                "--catalog-source",
                catalog_source,
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"kanon add exited {result.returncode} (expected 0).\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

        kanon_file = workspace / ".kanon"
        assert kanon_file.exists(), f".kanon file was not created at {kanon_file}."
        content = kanon_file.read_text()

        assert "<YOUR_GIT_ORG_BASE_URL>" not in content, (
            "kanon add wrote the literal placeholder <YOUR_GIT_ORG_BASE_URL> "
            "into .kanon (DEFECT-003).\n"
            f"Actual .kanon content:\n{content}"
        )

        assert "<true|false>" not in content, (
            "kanon add wrote the literal placeholder <true|false> "
            "into .kanon (DEFECT-003). Expected a concrete boolean value instead.\n"
            f"Actual .kanon content:\n{content}"
        )

        assert "KANON_SOURCE_foo_GITBASE=" not in content, (
            "this entry's manifest references no ${GITBASE}, so add must write no "
            f"per-dependency env-var line.\nActual .kanon content:\n{content}"
        )
        assert "KANON_SOURCE_foo_URL=" in content
        assert "KANON_SOURCE_foo_NAME=foo" in content


@pytest.mark.integration
class TestKanonInstallRejectsUnresolvedPlaceholder:
    """kanon install must fail fast when .kanon contains a literal `<...>` placeholder."""

    def test_install_fails_fast_when_kanon_header_contains_placeholder(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """kanon install exits non-zero + emits 'unresolved placeholder' diagnostic.

        Asserts three independent conditions, each of which can fail individually:

        1. `kanon install` exits with a non-zero status code.
        2. stderr contains the substring ``"unresolved placeholder"``.
        3. stderr names the 1-indexed line number of the offending ``GITBASE`` line.

        The `.kanon` is hand-written with:
        - ``GITBASE=<YOUR_GIT_ORG_BASE_URL>`` on line 1 (the offending placeholder)
        - A complete five-key ``KANON_SOURCE_foo_*`` block so the parser succeeds
          and install reaches the placeholder-validator step rather than failing
          on missing source variables.

        Against unfixed code the test fails because `kanon install` passes the
        literal placeholder through to `repo sync` and fails with a 404 or
        git-remote error, not with a structured "unresolved placeholder" diagnostic
        (DEFECT-003).
        """
        bare = _create_manifest_repo_with_tags(
            tmp_path / "catalog",
            entry_names=["foo"],
            tags=["1.0.0"],
        )
        catalog_source = f"file://{bare}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        kanon_content = textwrap.dedent(f"""\
            GITBASE=<YOUR_GIT_ORG_BASE_URL>
            CLAUDE_MARKETPLACES_DIR=${{HOME}}/.claude-marketplaces
            KANON_MARKETPLACE_INSTALL=false

            KANON_SOURCE_foo_URL={catalog_source}
            KANON_SOURCE_foo_REF=refs/heads/main
            KANON_SOURCE_foo_PATH=repos/foo
            KANON_SOURCE_foo_NAME=foo
            KANON_SOURCE_foo_GITBASE=https://example.com
            """)
        kanon_file = workspace / ".kanon"
        kanon_file.write_text(kanon_content)

        offending_line_number = 1

        env = dict(os.environ)
        env.pop("KANON_CATALOG_SOURCES", None)

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(workspace),
        )

        assert result.returncode != 0, (
            "kanon install exited 0 when the .kanon file contains the literal "
            "placeholder GITBASE=<YOUR_GIT_ORG_BASE_URL> (DEFECT-003). "
            "Expected a non-zero exit with an 'unresolved placeholder' diagnostic.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

        assert "unresolved placeholder" in result.stderr, (
            "kanon install did not emit 'unresolved placeholder' on stderr "
            "when .kanon contains GITBASE=<YOUR_GIT_ORG_BASE_URL> (DEFECT-003).\n"
            f"  exit code: {result.returncode}\n"
            f"  stderr   : {result.stderr!r}"
        )

        assert str(offending_line_number) in result.stderr, (
            f"kanon install stderr does not name the offending line number "
            f"({offending_line_number}) from .kanon (DEFECT-003).\n"
            f"  exit code: {result.returncode}\n"
            f"  stderr   : {result.stderr!r}"
        )
