"""Integration test: 'kanon why' ambiguity detection via subprocess.

Builds real file:// fixtures that intentionally force ambiguity:
  - A .kanon file declaring a source whose name normalizes to the same token
    as an XML manifest path after derive_source_name normalization.
  - A .kanon.lock encoding that tree.

Invokes 'kanon why <ambiguous-arg>' via subprocess and asserts:
  - Exit code is non-zero.
  - stderr names both interpretations (XML path AND source name).

Also tests the single-match paths (URL-only and XML-path-only) for completeness.

AC-TEST-002, AC-CYCLE-001
"""

import pathlib
import subprocess
import sys

import pytest

from tests.conftest import _make_minimal_kanon_file, _write_lockfile


@pytest.fixture(autouse=True)
def _mock_resolve_ref_to_sha():
    """Override: this test does not install anything -- no git calls needed."""
    yield


@pytest.fixture(autouse=True)
def _mock_check_sha_reachable():
    """Override: this test does not install anything -- no git calls needed."""
    yield


def _run_why(
    kanon_file: pathlib.Path,
    lock_file: pathlib.Path,
    target: str,
) -> subprocess.CompletedProcess:
    """Invoke 'kanon why <target>' via subprocess."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "kanon_cli",
            "why",
            target,
            "--kanon-file",
            str(kanon_file),
            "--lock-file",
            str(lock_file),
        ],
        capture_output=True,
        text=True,
    )


@pytest.mark.integration
class TestWhyAmbiguousXmlPathAndSourceName:
    """End-to-end: argument matches both XML path and source name -- hard error."""

    def test_ambiguity_xml_path_and_source_name_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """Argument matches XML path AND source name -> non-zero exit.

        Construction:
          - Source name: REPO_SPECS_FOO (normalize -> repo_specs_foo)
          - Argument: "Repo-Specs-Foo" (normalize -> repo_specs_foo) -- matches source name
          - Include node path_in_repo: "Repo-Specs-Foo" (exact string) -- matches XML path
        """
        source_name = "REPO_SPECS_FOO"
        ambiguous_arg = "Repo-Specs-Foo"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(tmp_path, source_name, project_url, include_path=ambiguous_arg)

        result = _run_why(kanon_file, lock_file, ambiguous_arg)

        assert result.returncode != 0, (
            f"Expected non-zero exit for ambiguous argument '{ambiguous_arg}'\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "ambiguous" in result.stderr.lower() or "multiple" in result.stderr.lower(), (
            f"stderr must mention ambiguity, got: {result.stderr!r}"
        )

    def test_ambiguity_error_message_lists_xml_path_interpretation(self, tmp_path: pathlib.Path) -> None:
        """Ambiguity error message names the XML path interpretation."""
        source_name = "REPO_SPECS_FOO"
        ambiguous_arg = "Repo-Specs-Foo"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(tmp_path, source_name, project_url, include_path=ambiguous_arg)

        result = _run_why(kanon_file, lock_file, ambiguous_arg)

        assert result.returncode != 0

        assert (
            "xml" in result.stderr.lower() or "manifest" in result.stderr.lower() or "path" in result.stderr.lower()
        ), f"stderr must mention XML path interpretation, got: {result.stderr!r}"

        assert ambiguous_arg in result.stderr, (
            f"stderr must contain the XML path '{ambiguous_arg}', got: {result.stderr!r}"
        )

    def test_ambiguity_error_message_lists_source_name_interpretation(self, tmp_path: pathlib.Path) -> None:
        """Ambiguity error message names the source name interpretation."""
        source_name = "REPO_SPECS_FOO"
        ambiguous_arg = "Repo-Specs-Foo"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(tmp_path, source_name, project_url, include_path=ambiguous_arg)

        result = _run_why(kanon_file, lock_file, ambiguous_arg)

        assert result.returncode != 0

        assert "source" in result.stderr.lower(), (
            f"stderr must mention source name interpretation, got: {result.stderr!r}"
        )

        assert source_name in result.stderr, (
            f"stderr must contain the source name '{source_name}', got: {result.stderr!r}"
        )

    def test_ambiguity_error_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Ambiguity error is written to stderr, not stdout."""
        source_name = "REPO_SPECS_FOO"
        ambiguous_arg = "Repo-Specs-Foo"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(tmp_path, source_name, project_url, include_path=ambiguous_arg)

        result = _run_why(kanon_file, lock_file, ambiguous_arg)

        assert result.returncode != 0
        assert result.stdout.strip() == "", f"stdout must be empty on ambiguity error, got: {result.stdout!r}"
        assert result.stderr.strip() != "", f"stderr must contain the error message, got: {result.stderr!r}"


@pytest.mark.integration
class TestWhyAmbiguousUrlAndXmlPath:
    """End-to-end: argument matches both URL and XML path -- hard error.

    This uses a file:// URL whose pathname happens to equal an XML manifest
    path in the tree (the spec notes this as "extremely unlikely but possible
    with file:// test fixtures").
    """

    def test_ambiguity_url_and_xml_path_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """Argument matches URL AND XML path -> non-zero exit.

        Construction:
          - Project URL: "file:///tmp/some/path.xml"
            canonical form = "file:///tmp/some/path.xml" (file:// passes through)
          - Include node path_in_repo: "file:///tmp/some/path.xml"
            (exact same string -- XML path matching is exact string equality)
        """
        source_name = "FOO"

        ambiguous_arg = "file:///tmp/some/path.xml"
        project_url = ambiguous_arg

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(
            tmp_path,
            source_name,
            project_url,
            include_path=ambiguous_arg,
        )

        result = _run_why(kanon_file, lock_file, ambiguous_arg)

        assert result.returncode != 0, (
            f"Expected non-zero exit for ambiguous argument '{ambiguous_arg}'\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_ambiguity_url_and_xml_path_error_lists_both(self, tmp_path: pathlib.Path) -> None:
        """Ambiguity error lists both URL and XML path interpretations."""
        source_name = "FOO"
        ambiguous_arg = "file:///tmp/some/path.xml"
        project_url = ambiguous_arg

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(
            tmp_path,
            source_name,
            project_url,
            include_path=ambiguous_arg,
        )

        result = _run_why(kanon_file, lock_file, ambiguous_arg)

        assert result.returncode != 0
        stderr = result.stderr

        assert "url" in stderr.lower() or "project" in stderr.lower(), (
            f"stderr must mention URL category, got: {stderr!r}"
        )

        assert "xml" in stderr.lower() or "manifest" in stderr.lower() or "path" in stderr.lower(), (
            f"stderr must mention XML path category, got: {stderr!r}"
        )


@pytest.mark.integration
class TestWhyUrlOnlyMatch:
    """End-to-end: argument matches only the URL category -- chain printed, exit 0.

    Serves as the AC-CYCLE-001 complement: after demonstrating ambiguity, changing
    the argument to match only the URL category should succeed with exit 0.
    """

    def test_url_only_match_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """URL-only argument: chain printed to stdout, exit 0."""
        source_name = "FOO"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(tmp_path, source_name, project_url)

        result = _run_why(kanon_file, lock_file, project_url)

        assert result.returncode == 0, (
            f"Expected exit 0 for URL-only match\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "FOO" in result.stdout, f"Chain must contain source name 'FOO', got: {result.stdout!r}"

    def test_url_only_match_chain_format(self, tmp_path: pathlib.Path) -> None:
        """URL-only match produces an arrow-separated chain line."""
        source_name = "FOO"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(tmp_path, source_name, project_url)

        result = _run_why(kanon_file, lock_file, project_url)

        assert result.returncode == 0
        assert " -> " in result.stdout

    def test_full_ac_cycle_001_ambiguity_then_url_disambiguation(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001: ambiguity then URL disambiguation.

        Step 1: Pass an argument that matches both XML path AND source name -> non-zero.
        Step 2: Pass the project URL explicitly -> exit 0 with chain on stdout.
        """
        source_name = "REPO_SPECS_FOO"
        ambiguous_arg = "Repo-Specs-Foo"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(tmp_path, source_name, project_url, include_path=ambiguous_arg)

        ambiguous_result = _run_why(kanon_file, lock_file, ambiguous_arg)
        assert ambiguous_result.returncode != 0, (
            f"Step 1: expected non-zero for ambiguous arg '{ambiguous_arg}'\nstderr: {ambiguous_result.stderr!r}"
        )
        assert "ambiguous" in ambiguous_result.stderr.lower() or "multiple" in ambiguous_result.stderr.lower(), (
            f"Step 1: stderr must describe ambiguity, got: {ambiguous_result.stderr!r}"
        )

        url_result = _run_why(kanon_file, lock_file, project_url)
        assert url_result.returncode == 0, (
            f"Step 2: expected exit 0 for URL '{project_url}'\n"
            f"stdout: {url_result.stdout!r}\nstderr: {url_result.stderr!r}"
        )
        lines = [ln for ln in url_result.stdout.splitlines() if ln.strip()]
        assert len(lines) >= 1, f"Step 2: expected at least 1 chain line, got: {lines!r}"

        assert source_name in url_result.stdout, (
            f"Step 2: chain must contain source name '{source_name}', got: {url_result.stdout!r}"
        )


@pytest.mark.integration
class TestWhySourceNameOnlyMatch:
    """End-to-end: argument matches only the source name category -- chain printed."""

    def test_source_name_match_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """Source-name-only argument: chain printed, exit 0."""
        source_name = "MY_SOURCE"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(tmp_path, source_name, project_url)

        result = _run_why(kanon_file, lock_file, "my-source")

        assert result.returncode == 0, (
            f"Expected exit 0 for source-name match\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "MY_SOURCE" in result.stdout, f"Chain must contain source name 'MY_SOURCE', got: {result.stdout!r}"

    def test_source_name_normalization_dash_matches(self, tmp_path: pathlib.Path) -> None:
        """Argument with dashes matches source name with underscores via derive_source_name."""
        source_name = "FOO_BAR"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(tmp_path, source_name, project_url)

        result = _run_why(kanon_file, lock_file, "Foo-Bar")

        assert result.returncode == 0, (
            f"Expected exit 0 for Foo-Bar -> FOO_BAR\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "FOO_BAR" in result.stdout


@pytest.mark.integration
class TestWhyXmlPathOnlyMatch:
    """End-to-end: argument matches only the XML path category -- chain printed."""

    def test_xml_path_match_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """XML-path-only argument: chain printed, exit 0."""
        source_name = "FOO"
        include_path = "repo-specs/unique.xml"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(tmp_path, source_name, project_url, include_path=include_path)

        result = _run_why(kanon_file, lock_file, include_path)

        assert result.returncode == 0, (
            f"Expected exit 0 for XML-path match\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert include_path in result.stdout, (
            f"Chain must contain include path '{include_path}', got: {result.stdout!r}"
        )

    def test_xml_path_is_exact_match(self, tmp_path: pathlib.Path) -> None:
        """Partial XML path does NOT match -- exit non-zero."""
        source_name = "FOO"
        include_path = "repo-specs/exact.xml"
        project_url = "https://github.com/org/proj"

        kanon_file = _make_minimal_kanon_file(tmp_path, source_name)
        lock_file = _write_lockfile(tmp_path, source_name, project_url, include_path=include_path)

        result = _run_why(kanon_file, lock_file, "exact.xml")

        assert result.returncode != 0, (
            f"Expected non-zero for partial XML path\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
