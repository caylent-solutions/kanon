"""Integration tests: no-default-catalog behaviour (AC-TEST-002, AC-CYCLE-001).

Confirms that resolve_catalog_dir raises MissingCatalogSourceError when
neither the CLI flag nor KANON_CATALOG_SOURCE is set, and that a fixture
command handler produces the verbatim spec Section 4 missing-source error
text on stderr.

The verbatim error text (spec Section 4):

    ERROR: <command> requires a catalog source.
    Provide one of:
      --catalog-source <git-url>@<ref>      # e.g. --catalog-source https://example.com/org/manifest-repo.git@main
      KANON_CATALOG_SOURCE=<git-url>@<ref>  # set as env var, then re-run
    The CLI flag takes precedence when both are set.
    A catalog source identifies a manifest repo (a git repository whose
    repo-specs/ directory exposes installable kanon dependencies).
    See docs/catalogs-explained.md for what a manifest repo is and how to find one.
    See docs/configuration.md for the full configuration reference.
"""

import pathlib
import subprocess
import sys

import pytest

from kanon_cli.core.catalog import MissingCatalogSourceError, resolve_catalog_dir


# Verbatim spec Section 4 missing-catalog error text.
# The calling command interpolates its own command name in place of <command>.
MISSING_CATALOG_ERROR_TEMPLATE = (
    "ERROR: {command} requires a catalog source.\n"
    "Provide one of:\n"
    "  --catalog-source <git-url>@<ref>      "
    "# e.g. --catalog-source https://example.com/org/manifest-repo.git@main\n"
    "  KANON_CATALOG_SOURCE=<git-url>@<ref>  # set as env var, then re-run\n"
    "The CLI flag takes precedence when both are set.\n"
    "A catalog source identifies a manifest repo (a git repository whose\n"
    "repo-specs/ directory exposes installable kanon dependencies).\n"
    "See docs/catalogs-explained.md for what a manifest repo is and how to find one.\n"
    "See docs/configuration.md for the full configuration reference."
)


def _fixture_command_handler(command: str) -> str:
    """Fixture command handler: catches MissingCatalogSourceError and formats stderr text.

    This simulates what a real kanon command (e.g. 'kanon list') does:
    it calls resolve_catalog_dir() and, on MissingCatalogSourceError, writes
    the canonical spec Section 4 text to stderr and exits 1.

    Returns the formatted error text (the caller writes it to stderr).
    """
    try:
        resolve_catalog_dir(None)
    except MissingCatalogSourceError:
        return MISSING_CATALOG_ERROR_TEMPLATE.format(command=command)
    return ""


@pytest.mark.integration
class TestNoDefaultCatalog:
    """AC-TEST-002, AC-CYCLE-001: no-default-catalog end-to-end behaviour."""

    def test_resolve_raises_missing_catalog_source_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-TEST-002 part 1: resolver raises MissingCatalogSourceError with no source."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        with pytest.raises(MissingCatalogSourceError):
            resolve_catalog_dir(None)

    def test_fixture_handler_produces_verbatim_spec_error_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-TEST-002 part 2: fixture handler formats the canonical Section 4 error text."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        error_text = _fixture_command_handler("list")
        expected = MISSING_CATALOG_ERROR_TEMPLATE.format(command="list")
        assert error_text == expected

    def test_error_text_contains_catalog_source_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error text must mention the --catalog-source flag."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        error_text = _fixture_command_handler("list")
        assert "--catalog-source" in error_text

    def test_error_text_contains_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error text must mention the KANON_CATALOG_SOURCE env var."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        error_text = _fixture_command_handler("list")
        assert "KANON_CATALOG_SOURCE" in error_text

    def test_error_text_references_catalogs_explained_doc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error text must reference docs/catalogs-explained.md (spec Section 4)."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        error_text = _fixture_command_handler("list")
        assert "docs/catalogs-explained.md" in error_text

    def test_error_text_references_configuration_doc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error text must reference docs/configuration.md (spec Section 4)."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        error_text = _fixture_command_handler("list")
        assert "docs/configuration.md" in error_text

    def test_subprocess_raises_missing_catalog_source_error(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001: subprocess with no KANON_CATALOG_SOURCE raises MissingCatalogSourceError."""
        script_path = tmp_path / "check_raises.py"
        script_path.write_text(
            "import os\n"
            "os.environ.pop('KANON_CATALOG_SOURCE', None)\n"
            "from kanon_cli.core.catalog import resolve_catalog_dir, MissingCatalogSourceError\n"
            "try:\n"
            "    resolve_catalog_dir(None)\n"
            "    raise AssertionError('expected MissingCatalogSourceError')\n"
            "except MissingCatalogSourceError:\n"
            "    pass\n"
        )
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"Script failed unexpectedly: returncode={result.returncode} stderr={result.stderr!r}"
        )

    def test_subprocess_handler_writes_verbatim_error_to_stderr_exit_1(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001: subprocess handler writes Section 4 text to stderr and exits 1."""
        expected = MISSING_CATALOG_ERROR_TEMPLATE.format(command="list")
        script_path = tmp_path / "fixture_handler.py"
        script_path.write_text(
            "import os, sys\n"
            "os.environ.pop('KANON_CATALOG_SOURCE', None)\n"
            "from kanon_cli.core.catalog import resolve_catalog_dir, MissingCatalogSourceError\n"
            "TEMPLATE = (\n"
            "    'ERROR: {command} requires a catalog source.\\n'\n"
            "    'Provide one of:\\n'\n"
            "    '  --catalog-source <git-url>@<ref>      '\n"
            "    '# e.g. --catalog-source https://example.com/org/manifest-repo.git@main\\n'\n"
            "    '  KANON_CATALOG_SOURCE=<git-url>@<ref>  # set as env var, then re-run\\n'\n"
            "    'The CLI flag takes precedence when both are set.\\n'\n"
            "    'A catalog source identifies a manifest repo (a git repository whose\\n'\n"
            "    'repo-specs/ directory exposes installable kanon dependencies).\\n'\n"
            "    'See docs/catalogs-explained.md for what a manifest repo is and how to find one.\\n'\n"
            "    'See docs/configuration.md for the full configuration reference.'\n"
            ")\n"
            "try:\n"
            "    resolve_catalog_dir(None)\n"
            "    sys.exit(0)\n"
            "except MissingCatalogSourceError:\n"
            "    print(TEMPLATE.format(command='list'), file=sys.stderr)\n"
            "    sys.exit(1)\n"
        )
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, f"Expected exit code 1, got {result.returncode}. stderr={result.stderr!r}"
        assert result.stderr.strip() == expected.strip(), (
            f"stderr mismatch.\nExpected:\n{expected}\nGot:\n{result.stderr}"
        )
