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
from urllib.parse import urlparse

import pytest

from tests.integration.test_add_core import (
    _create_manifest_repo_with_tags,
    _run_kanon,
)


def _bare_url_without_ref(catalog_source: str) -> str:
    """Strip the trailing @<ref> suffix from a catalog-source URL.

    Args:
        catalog_source: A catalog-source string of the form ``<url>@<ref>``.

    Returns:
        The URL portion with the ``@<ref>`` suffix removed.
    """
    at_idx = catalog_source.rfind("@")
    if at_idx == -1:
        return catalog_source
    return catalog_source[:at_idx]


def _derive_expected_gitbase(catalog_source: str) -> str:
    """Derive the expected GITBASE value from a catalog-source URL.

    Mirrors the derivation rule implemented in
    ``_derive_gitbase_from_catalog_source`` in ``commands/add.py``:

    - For ``https://``, ``http://``, and ``ssh://`` URLs: scheme + ``://``
      + netloc (authority) + the first path segment (org/owner prefix).
    - For ``file://`` URLs: netloc is empty, so the result is
      scheme + ``://`` + empty netloc + the parent directory of the path,
      e.g. ``file:///tmp/foo.git`` -> ``file:///tmp``.

    Args:
        catalog_source: A catalog-source string of the form ``<url>@<ref>``.

    Returns:
        The expected GITBASE value.
    """
    url = _bare_url_without_ref(catalog_source)
    parsed = urlparse(url)
    if parsed.scheme == "file":
        parent_path = str(pathlib.PurePosixPath(parsed.path).parent)
        return f"{parsed.scheme}://{parsed.netloc}{parent_path}"
    return f"{parsed.scheme}://{parsed.netloc}"


@pytest.mark.integration
class TestKanonAddNoPlaceholders:
    """kanon add must derive GITBASE from the catalog URL, not write literal placeholders."""

    def test_add_does_not_write_yourgitorgbaseurl_placeholder(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """kanon add writes a derived GITBASE, not literal `<YOUR_GIT_ORG_BASE_URL>`.

        Asserts three independent conditions, each of which can fail individually:

        1. The generated `.kanon` does NOT contain the literal string
           ``<YOUR_GIT_ORG_BASE_URL>``.
        2. The generated `.kanon` does NOT contain the literal string
           ``<true|false>``.
        3. The generated `.kanon` contains a ``KANON_SOURCE_foo_GITBASE=`` line
           whose value equals the org base derived from the catalog-source URL.

        Against unfixed code all three assertions fail because `kanon add`
        currently writes ``GITBASE=<YOUR_GIT_ORG_BASE_URL>`` and
        ``KANON_MARKETPLACE_INSTALL=<true|false>`` verbatim (DEFECT-003).
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
            "into .kanon (DEFECT-003). Expected a derived GITBASE value instead.\n"
            f"Actual .kanon content:\n{content}"
        )

        assert "<true|false>" not in content, (
            "kanon add wrote the literal placeholder <true|false> "
            "into .kanon (DEFECT-003). Expected a concrete boolean value instead.\n"
            f"Actual .kanon content:\n{content}"
        )

        expected_gitbase = _derive_expected_gitbase(catalog_source)
        gitbase_lines = [line for line in content.splitlines() if line.startswith("KANON_SOURCE_foo_GITBASE=")]
        assert gitbase_lines, (
            "No KANON_SOURCE_foo_GITBASE= line found in .kanon. "
            f"Expected a line starting with 'KANON_SOURCE_foo_GITBASE={expected_gitbase}'.\n"
            f"Actual .kanon content:\n{content}"
        )
        actual_gitbase_value = gitbase_lines[0].split("=", 1)[1]
        assert actual_gitbase_value == expected_gitbase, (
            f"GITBASE value mismatch.\n"
            f"  Expected: {expected_gitbase!r}\n"
            f"  Got     : {actual_gitbase_value!r}\n"
            f"Actual .kanon content:\n{content}"
        )


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
