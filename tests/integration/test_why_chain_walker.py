"""Integration test: 'kanon why' end-to-end with a real file:// fixture catalog.

Builds a real fixture:
  - A .kanon file referencing a top-level source named FOO.
  - A .kanon.lock file pinning every node (source FOO + include bar.xml + project baz).
  - The lockfile encodes the chain: FOO -> bar.xml (include) -> baz (project).

Invokes 'kanon why <baz-url>' via subprocess and asserts:
  - Exit code is 0.
  - stdout contains exactly one line.
  - The line follows the format: FOO -> bar.xml@<sha> -> baz@<sha>.
  - The SHAs in the output match the fixture lockfile values.

AC-TEST-002, AC-TEST-003, AC-CYCLE-001
"""

import pathlib
import subprocess
import sys
import textwrap

import pytest

from kanon_cli.core.lockfile import (
    CURRENT_SCHEMA_VERSION,
    IncludeEntry,
    Lockfile,
    ProjectEntry,
    SourceEntry,
    write_lockfile,
)
from kanon_cli.core.url import canonicalize_repo_url


# ---------------------------------------------------------------------------
# Fixture constants
# ---------------------------------------------------------------------------

_SOURCE_NAME = "FOO"
_PROJECT_NAME = "baz"
_PROJECT_URL = "https://github.com/org/baz"
_INCLUDE_NAME = "bar"
_INCLUDE_PATH = "repo-specs/bar.xml"

# Fixed SHAs used throughout the fixture -- 40 hex chars each
_SOURCE_SHA = "a" * 40
_INCLUDE_SHA = "c" * 40
_PROJECT_SHA = "b" * 40
_KANON_HASH = "sha256:" + "a" * 64


# ---------------------------------------------------------------------------
# Override conftest autouse fixtures (not needed for this test)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_resolve_ref_to_sha():
    """Override: this test does not install anything -- no git calls needed."""
    yield


@pytest.fixture(autouse=True)
def _mock_check_sha_reachable():
    """Override: this test does not install anything -- no git calls needed."""
    yield


# ---------------------------------------------------------------------------
# Fixture: .kanon and .kanon.lock in a tmp directory
# ---------------------------------------------------------------------------


@pytest.fixture()
def why_fixture(tmp_path: pathlib.Path):
    """Create a .kanon file and a .kanon.lock with a single include chain.

    Tree structure in the lockfile:
      FOO (source, sha=_SOURCE_SHA)
        bar (include, path_in_repo=_INCLUDE_PATH, sha=_INCLUDE_SHA)
          (no nested includes)
        baz (project, url=_PROJECT_URL, sha=_PROJECT_SHA)

    Returns:
        A dict with keys 'kanon_file', 'lock_file', 'project_url', 'project_sha',
        'include_sha', 'include_path', 'source_name'.
    """
    kanon_file = tmp_path / ".kanon"
    kanon_content = textwrap.dedent(f"""\
        KANON_SOURCE_{_SOURCE_NAME}_URL=https://github.com/org/catalog
        KANON_SOURCE_{_SOURCE_NAME}_REF=main
        KANON_SOURCE_{_SOURCE_NAME}_PATH=./foo
        KANON_SOURCE_{_SOURCE_NAME}_NAME={_SOURCE_NAME}
        KANON_SOURCE_{_SOURCE_NAME}_GITBASE=https://example.com
    """)
    kanon_file.write_text(kanon_content)
    kanon_file.chmod(0o644)

    lockfile = Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2024-01-01T00:00:00Z",
        generator="kanon-test",
        kanon_hash=_KANON_HASH,
        sources=[
            SourceEntry(
                alias=_SOURCE_NAME,
                name=_SOURCE_NAME,
                url="https://github.com/org/catalog",
                ref_spec="main",
                resolved_ref="refs/heads/main",
                resolved_sha=_SOURCE_SHA,
                path="./foo",
                includes=[
                    IncludeEntry(
                        name=_INCLUDE_NAME,
                        path_in_repo=_INCLUDE_PATH,
                        url="https://github.com/org/catalog",
                        resolved_sha=_INCLUDE_SHA,
                        includes=[],
                    )
                ],
                projects=[
                    ProjectEntry(
                        name=_PROJECT_NAME,
                        url=_PROJECT_URL,
                        canonical_url=canonicalize_repo_url(_PROJECT_URL),
                        ref_spec="main",
                        resolved_ref="refs/heads/main",
                        resolved_sha=_PROJECT_SHA,
                    )
                ],
            )
        ],
    )

    lock_file = tmp_path / ".kanon.lock"
    write_lockfile(lockfile, lock_file)

    return {
        "kanon_file": kanon_file,
        "lock_file": lock_file,
        "project_url": _PROJECT_URL,
        "project_sha": _PROJECT_SHA,
        "include_sha": _INCLUDE_SHA,
        "include_path": _INCLUDE_PATH,
        "source_name": _SOURCE_NAME,
    }


# ---------------------------------------------------------------------------
# End-to-end tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWhyChainWalkerIntegration:
    """End-to-end integration tests for 'kanon why' via subprocess."""

    def _run_why(
        self,
        fixture: dict,
        url: str | None = None,
    ) -> subprocess.CompletedProcess:
        """Build and run the 'kanon why' subprocess for the given fixture.

        Args:
            fixture: The why_fixture dict with 'kanon_file', 'lock_file', and 'project_url'.
            url: The target URL to pass to 'kanon why'. Defaults to fixture['project_url'].

        Returns:
            The CompletedProcess result from subprocess.run.
        """
        target = url if url is not None else fixture["project_url"]
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "kanon_cli",
                "why",
                target,
                "--kanon-file",
                str(fixture["kanon_file"]),
                "--lock-file",
                str(fixture["lock_file"]),
            ],
            capture_output=True,
            text=True,
        )

    def test_single_chain_via_subprocess(self, why_fixture: dict) -> None:
        """kanon why <project-url> prints annotation + alias-render + one chain line (AC-TEST-002, AC-TEST-003).

        After the match-annotation and alias-render enhancements the output is three non-empty lines:
          Line 1: matched <category> '<token>'
          Line 2: <alias> -> <name> from <url>@<ref>
          Line 3: <chain>
        """
        result = self._run_why(why_fixture)

        assert result.returncode == 0, (
            f"kanon why exited {result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert len(lines) == 3, (
            f"Expected 3 output lines (annotation + alias-render + chain), got {len(lines)}: {lines!r}"
        )
        assert lines[0].startswith("matched "), (
            f"First line must be the match annotation starting with 'matched ', got: {lines[0]!r}"
        )

    def test_chain_contains_source_name(self, why_fixture: dict) -> None:
        """Output chain line (last line) must start with the top-level source name (AC-FUNC-002).

        The first output line is the match annotation, then one alias-render line
        (<alias> -> <name> from <url>@<ref>), and the last line is the chain.
        """
        result = self._run_why(why_fixture)

        assert result.returncode == 0
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert len(lines) >= 3, f"Expected annotation + alias-render + chain line, got: {lines!r}"
        chain_line = lines[-1]
        assert chain_line.startswith(why_fixture["source_name"]), (
            f"Chain line must start with source name {why_fixture['source_name']!r}, got: {chain_line!r}"
        )

    def test_chain_contains_project_sha(self, why_fixture: dict) -> None:
        """Output chain must contain the project SHA from the lockfile (AC-FUNC-004)."""
        result = self._run_why(why_fixture)

        assert result.returncode == 0
        line = result.stdout.strip()
        expected_suffix = f"{_PROJECT_NAME}@{why_fixture['project_sha']}"
        assert expected_suffix in line, f"Chain line must contain '{expected_suffix}', got: {line!r}"

    def test_chain_contains_project_name_and_sha(self, why_fixture: dict) -> None:
        """Output chain must contain the project name and SHA from the lockfile."""
        result = self._run_why(why_fixture)

        assert result.returncode == 0
        line = result.stdout.strip()
        expected_segment = f"{_PROJECT_NAME}@{why_fixture['project_sha']}"
        assert expected_segment in line, f"Chain line must contain '{expected_segment}', got: {line!r}"

    def test_chain_uses_arrow_separator(self, why_fixture: dict) -> None:
        """Output chain must use ' -> ' as separator (AC-FUNC-002)."""
        result = self._run_why(why_fixture)

        assert result.returncode == 0
        line = result.stdout.strip()
        assert " -> " in line, f"Chain line must use ' -> ' separator, got: {line!r}"

    def test_not_found_exits_nonzero(self, why_fixture: dict) -> None:
        """Absent URL exits non-zero with error message (AC-FUNC-007)."""
        absent_url = "https://github.com/org/does-not-exist"
        result = self._run_why(why_fixture, url=absent_url)

        assert result.returncode != 0, "kanon why with absent URL must exit non-zero"
        assert "not found" in result.stderr.lower(), f"stderr must contain 'not found', got: {result.stderr!r}"
        assert absent_url in result.stderr, f"stderr must name the missing URL, got: {result.stderr!r}"

    def test_scp_url_canonicalization_matches(self, why_fixture: dict) -> None:
        """SCP shorthand git@github.com:org/baz.git matches the https:// project URL (AC-FUNC-003).

        After the match-annotation and alias-render enhancements the output is three non-empty lines:
          Line 1: matched <category> '<token>'
          Line 2: <alias> -> <name> from <url>@<ref>
          Line 3: <chain>
        """
        scp_url = "git@github.com:org/baz.git"
        result = self._run_why(why_fixture, url=scp_url)

        assert result.returncode == 0, (
            f"kanon why with SCP URL must exit 0\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert len(lines) == 3, f"Expected annotation + alias-render + chain line, got {len(lines)}: {lines!r}"
        assert lines[0].startswith("matched "), f"First line must be the match annotation, got: {lines[0]!r}"

    def test_full_ac_cycle_001(self, why_fixture: dict) -> None:
        """AC-CYCLE-001: full cycle -- build fixture, invoke kanon why, assert output shape.

        Fixture: source FOO has include bar.xml (path_in_repo=repo-specs/bar.xml,
        sha=ccc...) and project baz (sha=bbb...) in its lockfile entry.
        .kanon references FOO. .kanon.lock pins every node.
        Invoke: kanon why <baz-url>.
        Assert: stdout contains exactly three non-empty lines:
          Line 1: match annotation (e.g. "matched url '<canonical-url>'")
          Line 2: alias-render "FOO -> FOO from <url>@<ref>"
          Line 3: the full include-node chain FOO -> repo-specs/bar.xml@<sha> -> baz@<sha>
        with exit code 0.
        """
        result = self._run_why(why_fixture)

        assert result.returncode == 0, f"Exit code must be 0\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"

        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert len(lines) == 3, f"Expected annotation + alias-render + chain line (3 lines), got: {lines!r}"

        # Line 0 is the match annotation
        annotation_line = lines[0]
        assert annotation_line.startswith("matched "), (
            f"First line must be the match annotation, got: {annotation_line!r}"
        )

        # Line 1 is the alias-render: "<alias> -> <name> from <url>@<ref>"
        alias_render_line = lines[1]
        assert alias_render_line.startswith(f"{_SOURCE_NAME} -> "), (
            f"Second line must be the alias-render for {_SOURCE_NAME!r}, got: {alias_render_line!r}"
        )

        # Line 2 is the chain
        chain_line = lines[2]

        # Source at start
        assert chain_line.startswith(_SOURCE_NAME), f"Chain must start with '{_SOURCE_NAME}', got: {chain_line!r}"

        # Include node segment: <include-path>@<include-sha>
        expected_include_segment = f"{_INCLUDE_PATH}@{why_fixture['include_sha']}"
        assert expected_include_segment in chain_line, (
            f"Chain line must contain include-node segment '{expected_include_segment}', got: {chain_line!r}"
        )

        # Project name with its SHA at end
        expected_project_segment = f"{_PROJECT_NAME}@{_PROJECT_SHA}"
        assert chain_line.endswith(expected_project_segment), (
            f"Chain must end with '{expected_project_segment}', got: {chain_line!r}"
        )

        # Full chain shape: FOO -> repo-specs/bar.xml@<sha> -> baz@<sha>
        expected_chain = (
            f"{_SOURCE_NAME} -> {_INCLUDE_PATH}@{why_fixture['include_sha']} -> {_PROJECT_NAME}@{_PROJECT_SHA}"
        )
        assert chain_line == expected_chain, f"Full chain must be '{expected_chain}', got: {chain_line!r}"
